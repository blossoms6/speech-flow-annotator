from __future__ import annotations

import math
import uuid
from collections import Counter

import numpy as np

from app.audio import AcousticFeatures, AudioData, boundary_energy, release_burst_score
from app.schemas import Annotation, Phrase, Word
from app.text import final_letter, initial_letter


FUNCTION_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "could",
    "do", "does", "for", "from", "had", "has", "have", "he", "her", "him", "his", "i",
    "in", "is", "it", "me", "must", "my", "of", "on", "or", "our", "shall", "she",
    "should", "some", "than", "that", "the", "their", "them", "there", "they", "this",
    "to", "us", "was", "we", "were", "will", "would", "you", "your",
}

WEAK_FORMS = {
    "a": "/ə/", "an": "/ən/", "and": "/ən/", "are": "/ə/", "as": "/əz/",
    "at": "/ət/", "be": "/bi/", "been": "/bɪn/", "but": "/bət/", "can": "/kən/",
    "could": "/kəd/", "do": "/də/", "does": "/dəz/", "for": "/fər/", "from": "/frəm/",
    "had": "/həd/", "has": "/həz/", "have": "/həv/", "he": "/i/", "her": "/ər/",
    "him": "/ɪm/", "is": "/əz/", "me": "/mi/", "must": "/məst/", "of": "/əv/",
    "or": "/ər/", "shall": "/ʃəl/", "she": "/ʃi/", "should": "/ʃəd/", "some": "/səm/",
    "than": "/ðən/", "that": "/ðət/", "the": "/ðə/", "them": "/ðəm/", "to": "/tə/",
    "us": "/əs/", "was": "/wəz/", "we": "/wi/", "were": "/wər/", "will": "/wəl/",
    "would": "/wəd/", "you": "/jə/", "your": "/jər/",
}

VOWELS = set("aeiou")
CONSONANTS = set("bcdfghjklmnpqrstvwxyz")
STOP_CONSONANTS = set("ptkbdg")


def _annotation(
    kind: str,
    start_word: int,
    end_word: int,
    label: str,
    symbol: str,
    confidence: float,
    experimental: bool = False,
    evidence: dict | None = None,
) -> Annotation:
    return Annotation(
        id=uuid.uuid4().hex[:12],
        type=kind,
        start_word=start_word,
        end_word=end_word,
        label=label,
        symbol=symbol,
        confidence=round(float(np.clip(confidence, 0.0, 1.0)), 3),
        experimental=experimental,
        evidence=evidence or {},
    )


def _safe_zscore(values: list[float | None]) -> np.ndarray:
    array = np.array([np.nan if value is None else float(value) for value in values], dtype=float)
    valid = np.isfinite(array)
    result = np.zeros(len(array), dtype=float)
    if np.count_nonzero(valid) < 2:
        return result
    median = np.nanmedian(array)
    scale = np.nanmedian(np.abs(array - median)) * 1.4826
    if scale < 1e-6:
        scale = np.nanstd(array)
    if scale < 1e-6:
        return result
    result[valid] = (array[valid] - median) / scale
    return np.clip(result, -3.0, 3.0)


def analyze_prominence(words: list[Word]) -> tuple[list[Annotation], dict[int, float]]:
    f0 = [word.acoustic.get("f0_peak") for word in words]
    intensity = [word.acoustic.get("intensity_mean") for word in words]
    duration = [max(0.03, word.end - word.start) / max(1, word.syllables) for word in words]
    f0_z = _safe_zscore(f0)
    intensity_z = _safe_zscore(intensity)
    duration_z = _safe_zscore(duration)
    annotations: list[Annotation] = []
    scores: dict[int, float] = {}

    for index, word in enumerate(words):
        prior = -0.75 if word.normalized in FUNCTION_WORDS else 0.28
        raw = 0.58 * f0_z[index] + 0.52 * intensity_z[index] + 0.58 * duration_z[index] + prior
        score = 1.0 / (1.0 + math.exp(-raw))
        scores[index] = round(score, 3)
        if score >= 0.61:
            confidence = min(0.95, 0.52 + abs(score - 0.5) * 1.25)
            annotations.append(
                _annotation(
                    "prominence",
                    index,
                    index,
                    "主要重音" if score >= 0.74 else "次重音",
                    "●" if score >= 0.74 else "•",
                    confidence,
                    evidence={
                        "prominence_score": round(score, 3),
                        "pitch_zscore": round(float(f0_z[index]), 3),
                        "intensity_zscore": round(float(intensity_z[index]), 3),
                        "duration_zscore": round(float(duration_z[index]), 3),
                    },
                )
            )
    return annotations, scores


def analyze_pauses(words: list[Word]) -> list[Annotation]:
    annotations: list[Annotation] = []
    for index, word in enumerate(words[:-1]):
        gap = max(0.0, words[index + 1].start - word.end)
        punctuation = word.punctuation_after
        if gap >= 0.48:
            label, symbol, confidence = "长停顿", "//", min(0.99, 0.76 + gap * 0.25)
        elif gap >= 0.18:
            label, symbol, confidence = "短停顿", "/", min(0.97, 0.72 + gap * 0.35)
        elif punctuation and any(mark in punctuation for mark in ",;:—"):
            label, symbol, confidence = "意群边界", "/", 0.62
        elif punctuation and any(mark in punctuation for mark in ".!?"):
            label, symbol, confidence = "句末边界", "//", 0.72
        else:
            continue
        annotations.append(
            _annotation(
                "pause",
                index,
                index,
                label,
                symbol,
                confidence,
                evidence={"silence_ms": round(gap * 1000), "punctuation": punctuation},
            )
        )
    if words:
        last = words[-1]
        annotations.append(
            _annotation("phrase_boundary", last.index, last.index, "文稿结束", "//", 0.99)
        )
    return annotations


def make_phrases(words: list[Word], pauses: list[Annotation], max_words: int = 14) -> list[Phrase]:
    if not words:
        return []
    boundary_indices = {
        item.end_word for item in pauses if item.symbol in {"/", "//"} or item.type == "phrase_boundary"
    }
    phrases: list[Phrase] = []
    start = 0
    for index in range(len(words)):
        forced = index - start + 1 >= max_words
        if index in boundary_indices or forced or index == len(words) - 1:
            segment = words[start : index + 1]
            text = " ".join(word.text + word.punctuation_after for word in segment)
            phrases.append(
                Phrase(
                    index=len(phrases),
                    start_word=start,
                    end_word=index,
                    start=segment[0].start,
                    end=segment[-1].end,
                    text=text,
                )
            )
            start = index + 1
    return phrases


def analyze_intonation(
    phrases: list[Phrase],
    features: AcousticFeatures,
) -> list[Annotation]:
    annotations: list[Annotation] = []
    for phrase in phrases:
        start = phrase.start + (phrase.end - phrase.start) * 0.55
        mask = (features.times >= start) & (features.times <= phrase.end) & (features.f0_hz > 0)
        times = features.times[mask]
        pitch = features.f0_hz[mask]
        if len(pitch) < 4:
            phrase.intonation = "unknown"
            phrase.intonation_symbol = "·"
            phrase.confidence = 0.25
            continue
        reference = float(np.median(pitch))
        semitones = 12.0 * np.log2(np.maximum(pitch, 1.0) / reference)
        normalized_times = times - times[0]
        slope = float(np.polyfit(normalized_times, semitones, 1)[0]) if times[-1] > times[0] else 0.0
        third = max(1, len(semitones) // 3)
        movement = float(np.median(semitones[-third:]) - np.median(semitones[:third]))
        combined = movement + slope * min(0.4, float(times[-1] - times[0])) * 0.45
        if combined >= 0.85:
            name, symbol = "升调", "↗"
        elif combined <= -0.85:
            name, symbol = "降调", "↘"
        else:
            name, symbol = "延续/平调", "→"
        confidence = min(0.94, 0.55 + abs(combined) * 0.12 + min(0.15, len(pitch) / 100))
        phrase.intonation = name
        phrase.intonation_symbol = symbol
        phrase.confidence = round(confidence, 3)
        annotations.append(
            _annotation(
                "intonation",
                phrase.start_word,
                phrase.end_word,
                name,
                symbol,
                confidence,
                evidence={
                    "movement_semitones": round(movement, 3),
                    "slope_semitones_per_second": round(slope, 3),
                    "voiced_frames": int(len(pitch)),
                },
            )
        )
    return annotations


def analyze_rhythm(
    words: list[Word], phrases: list[Phrase], prominence_scores: dict[int, float]
) -> tuple[list[Annotation], dict]:
    stress_times: list[float] = []
    annotations: list[Annotation] = []
    total_syllables = sum(word.syllables for word in words)
    speech_duration = max(0.01, words[-1].end - words[0].start) if words else 0.01

    for phrase in phrases:
        symbols: list[str] = []
        stressed_words: list[str] = []
        for index in range(phrase.start_word, phrase.end_word + 1):
            score = prominence_scores.get(index, 0.0)
            strong = score >= 0.61
            symbols.extend(["●" if strong and syllable == word_syllable - 1 else "·" for word_syllable in [words[index].syllables] for syllable in range(word_syllable)])
            if strong:
                stress_times.append((words[index].start + words[index].end) / 2)
                stressed_words.append(words[index].text)
        phrase.rhythm_pattern = " ".join(symbols)
        annotations.append(
            _annotation(
                "rhythm",
                phrase.start_word,
                phrase.end_word,
                "强弱节奏",
                phrase.rhythm_pattern,
                0.72,
                evidence={"stressed_words": stressed_words, "syllable_count": len(symbols)},
            )
        )

    intervals = np.diff(stress_times).tolist() if len(stress_times) > 1 else []
    summary = {
        "syllables": total_syllables,
        "syllables_per_second": round(total_syllables / speech_duration, 2),
        "mean_stress_interval": round(float(np.mean(intervals)), 3) if intervals else None,
        "stress_intervals": [round(float(value), 3) for value in intervals],
    }
    return annotations, summary


def analyze_weak_forms(words: list[Word], prominence_scores: dict[int, float]) -> list[Annotation]:
    annotations: list[Annotation] = []
    durations = np.array([(word.end - word.start) / max(1, word.syllables) for word in words])
    median_duration = float(np.median(durations)) if len(durations) else 0.18
    intensities = [word.acoustic.get("intensity_mean") for word in words]
    valid_intensities = [float(value) for value in intensities if value is not None]
    median_intensity = float(np.median(valid_intensities)) if valid_intensities else -25.0

    for index, word in enumerate(words):
        pronunciation = WEAK_FORMS.get(word.normalized)
        if not pronunciation:
            continue
        prominence = prominence_scores.get(index, 0.5)
        duration = durations[index]
        intensity = intensities[index]
        duration_factor = float(np.clip((median_duration - duration) / max(median_duration, 0.05), -1, 1))
        intensity_factor = 0.0 if intensity is None else float(np.clip((median_intensity - intensity) / 8.0, -1, 1))
        score = 0.52 * (1.0 - prominence) + 0.22 * max(0, duration_factor) + 0.12 * max(0, intensity_factor)
        if score < 0.39:
            continue
        confidence = min(0.84, 0.42 + score * 0.55)
        annotations.append(
            _annotation(
                "weak_form",
                index,
                index,
                f"可能弱读为 {pronunciation}",
                pronunciation,
                confidence,
                experimental=True,
                evidence={
                    "prominence_score": prominence,
                    "duration_ms": round(duration * 1000),
                    "duration_vs_median": round(duration_factor, 3),
                    "intensity_vs_median": round(intensity_factor, 3),
                    "note": "1.0使用韵律与功能词规则生成候选，未执行独立音素识别。",
                },
            )
        )
    return annotations


def analyze_linking(words: list[Word], audio: AudioData) -> list[Annotation]:
    annotations: list[Annotation] = []
    global_rms = float(np.sqrt(np.mean(audio.samples * audio.samples) + 1e-9))
    for index, current in enumerate(words[:-1]):
        following = words[index + 1]
        gap = max(0.0, following.start - current.end)
        if gap > 0.09 or current.punctuation_after:
            continue
        final = final_letter(current.text)
        initial = initial_letter(following.text)
        if not final or not initial:
            continue
        if final in CONSONANTS and initial in VOWELS:
            label = "辅音＋元音连读候选"
            subtype = "consonant_vowel"
        elif final in VOWELS and initial in VOWELS:
            label = "元音＋元音衔接候选"
            subtype = "vowel_vowel"
        elif final == initial and final in CONSONANTS:
            label = "相同辅音融合候选"
            subtype = "consonant_merger"
        else:
            continue
        energy = boundary_energy(audio, (current.end + following.start) / 2)
        continuity = float(np.clip(energy / max(global_rms, 1e-5), 0, 1.5) / 1.5)
        confidence = min(0.86, 0.48 + (0.09 - gap) * 2.0 + continuity * 0.18)
        annotations.append(
            _annotation(
                "linking",
                index,
                index + 1,
                label,
                "‿",
                confidence,
                experimental=True,
                evidence={
                    "subtype": subtype,
                    "interword_gap_ms": round(gap * 1000),
                    "boundary_energy_ratio": round(continuity, 3),
                    "note": "1.0检测连续发音环境；高精度音变确认需要音素识别模型。",
                },
            )
        )
    return annotations


def analyze_unreleased_stops(words: list[Word], audio: AudioData) -> list[Annotation]:
    annotations: list[Annotation] = []
    for index, current in enumerate(words[:-1]):
        following = words[index + 1]
        final = final_letter(current.text)
        initial = initial_letter(following.text)
        gap = max(0.0, following.start - current.end)
        if final not in STOP_CONSONANTS or initial not in CONSONANTS or gap > 0.14:
            continue
        burst = release_burst_score(audio, current.end)
        if burst >= 0.48:
            continue
        confidence = min(0.76, 0.48 + (0.48 - burst) * 0.42 + (0.14 - gap) * 0.3)
        annotations.append(
            _annotation(
                "unreleased_stop",
                index,
                index,
                f"词尾 /{final}/ 可能不完全释放",
                f"{final}̚",
                confidence,
                experimental=True,
                evidence={
                    "following_sound": initial,
                    "interword_gap_ms": round(gap * 1000),
                    "release_burst_score": round(burst, 3),
                    "note": "失爆为实验性声学候选，不等同于确认省音。",
                },
            )
        )
    return annotations


def run_all_analyzers(
    words: list[Word], features: AcousticFeatures, audio: AudioData
) -> tuple[list[Phrase], list[Annotation], dict]:
    prominence, prominence_scores = analyze_prominence(words)
    pauses = analyze_pauses(words)
    phrases = make_phrases(words, pauses)

    # Ensure a readable rhythm anchor when a phrase has no detected prominence.
    for phrase in phrases:
        if not any(prominence_scores.get(index, 0) >= 0.61 for index in range(phrase.start_word, phrase.end_word + 1)):
            candidates = [
                index for index in range(phrase.start_word, phrase.end_word + 1)
                if words[index].normalized not in FUNCTION_WORDS
            ] or list(range(phrase.start_word, phrase.end_word + 1))
            selected = max(candidates, key=lambda index: prominence_scores.get(index, 0))
            prominence_scores[selected] = 0.62
            prominence.append(
                _annotation("prominence", selected, selected, "节奏重音", "●", 0.55,
                            evidence={"prominence_score": 0.62, "fallback": True})
            )

    intonation = analyze_intonation(phrases, features)
    rhythm, rhythm_summary = analyze_rhythm(words, phrases, prominence_scores)
    weak_forms = analyze_weak_forms(words, prominence_scores)
    linking = analyze_linking(words, audio)
    unreleased = analyze_unreleased_stops(words, audio)
    annotations = pauses + prominence + rhythm + intonation + weak_forms + linking + unreleased
    annotations.sort(key=lambda item: (item.start_word, item.end_word, item.type))
    counts = Counter(item.type for item in annotations)
    summary = {
        "counts": dict(counts),
        "rhythm": rhythm_summary,
        "experimental_notice": "弱读、连读和失爆为1.0实验性候选，必须结合原音复核。",
    }
    return phrases, annotations, summary
