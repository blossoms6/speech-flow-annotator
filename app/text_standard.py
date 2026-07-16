from __future__ import annotations

import uuid
from collections import Counter
from functools import lru_cache

import cmudict

from app import __version__
from app.analyzers import FUNCTION_WORDS, STOP_CONSONANTS, VOWELS, WEAK_FORMS
from app.schemas import AnalysisResult, Annotation, Phrase, Word
from app.store import utc_now
from app.text import final_letter, initial_letter, normalize_transcript, syllable_count, tokenize_transcript


WH_WORDS = {"what", "when", "where", "which", "who", "whom", "whose", "why", "how"}
CLAUSE_MARKS = {",", ";", ":", ".", "!", "?", "—"}


@lru_cache(maxsize=1)
def pronunciation_dictionary() -> dict[str, list[list[str]]]:
    return cmudict.dict()


def pronunciation_for(word: str) -> tuple[str | None, list[int]]:
    entries = pronunciation_dictionary().get(word.lower().replace("’", "'"), [])
    if not entries:
        count = syllable_count(word)
        if count == 1:
            return None, [1]
        weak_prefixes = ("a", "be", "con", "de", "re", "to")
        stress_index = 1 if word.lower().startswith(weak_prefixes) else 0
        return None, [1 if index == stress_index else 0 for index in range(count)]
    phones = entries[0]
    stresses = [int(phone[-1]) for phone in phones if phone[-1:].isdigit()]
    return " ".join(phones), stresses or [1]


def make_standard_words(transcript: str) -> list[Word]:
    tokens = tokenize_transcript(transcript)
    if not tokens:
        raise ValueError("没有检测到可生成朗读稿的英文单词。")
    words: list[Word] = []
    cursor = 0.0
    for index, token in enumerate(tokens):
        pronunciation, stresses = pronunciation_for(token.normalized)
        count = max(1, len(stresses), syllable_count(token.text))
        if len(stresses) < count:
            stresses += [0] * (count - len(stresses))
        duration = 0.16 + count * 0.23 + min(0.12, len(token.text) * 0.008)
        words.append(
            Word(
                index=index,
                text=token.text,
                normalized=token.normalized,
                punctuation_after=token.punctuation_after,
                start=round(cursor, 3),
                end=round(cursor + duration, 3),
                confidence=0.82,
                alignment_method="standard-reading-plan",
                syllables=count,
                pronunciation=pronunciation,
                lexical_stress=stresses[:count],
                acoustic={"duration": round(duration, 3)},
            )
        )
        cursor += duration
        if any(mark in token.punctuation_after for mark in ",;:—"):
            cursor += 0.28
        elif any(mark in token.punctuation_after for mark in ".!?"):
            cursor += 0.52
        else:
            cursor += 0.035
    return words


def annotation(
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
        confidence=confidence,
        experimental=experimental,
        evidence=evidence or {},
    )


def standard_phrases(words: list[Word], max_words: int = 12) -> list[Phrase]:
    phrases: list[Phrase] = []
    start = 0
    for index, word in enumerate(words):
        punctuation_boundary = any(mark in word.punctuation_after for mark in CLAUSE_MARKS)
        length_boundary = index - start + 1 >= max_words
        if punctuation_boundary or length_boundary or index == len(words) - 1:
            segment = words[start : index + 1]
            phrases.append(
                Phrase(
                    index=len(phrases),
                    start_word=start,
                    end_word=index,
                    start=segment[0].start,
                    end=segment[-1].end,
                    text=" ".join(item.text + item.punctuation_after for item in segment),
                )
            )
            start = index + 1
    return phrases


def suggested_tone(phrase: Phrase, words: list[Word], is_last: bool) -> tuple[str, str, float]:
    last_word = words[phrase.end_word]
    first_word = words[phrase.start_word].normalized
    punctuation = last_word.punctuation_after
    if "?" in punctuation:
        if first_word in WH_WORDS:
            return "标准疑问降调", "↘", 0.88
        return "一般疑问升调", "↗", 0.86
    if "!" in punctuation or "." in punctuation or is_last:
        return "陈述句降调", "↘", 0.9
    if any(mark in punctuation for mark in ",;:—"):
        return "未完意群延续调", "↗", 0.8
    return "延续调", "→", 0.72


def analyze_standard_text(words: list[Word]) -> tuple[list[Phrase], list[Annotation], dict]:
    phrases = standard_phrases(words)
    annotations: list[Annotation] = []

    for phrase_index, phrase in enumerate(phrases):
        content = [
            index for index in range(phrase.start_word, phrase.end_word + 1)
            if words[index].normalized not in FUNCTION_WORDS
        ]
        if words[phrase.start_word].normalized in WH_WORDS:
            content.insert(0, phrase.start_word)
            content = list(dict.fromkeys(content))
        if not content:
            content = [phrase.end_word]
        focus_word = content[-1]

        rhythm_symbols: list[str] = []
        for index in range(phrase.start_word, phrase.end_word + 1):
            word = words[index]
            is_content = index in content
            pattern = word.lexical_stress or [1] + [0] * (word.syllables - 1)
            for stress in pattern[: word.syllables]:
                rhythm_symbols.append("●" if is_content and stress > 0 else "·")
            if is_content:
                main = index == focus_word
                annotations.append(
                    annotation(
                        "prominence",
                        index,
                        index,
                        "标准句子主重音" if main else "标准内容词重音",
                        "●" if main else "•",
                        0.9 if main else 0.78,
                        evidence={
                            "source": "standard-reading-rule",
                            "lexical_stress": pattern,
                            "focus_word": main,
                        },
                    )
                )
            weak = WEAK_FORMS.get(word.normalized)
            if weak and not is_content and index != phrase.end_word:
                annotations.append(
                    annotation(
                        "weak_form",
                        index,
                        index,
                        f"标准自然朗读建议弱读为 {weak}",
                        weak,
                        0.82,
                        evidence={"source": "standard-reading-rule", "not_observed_audio": True},
                    )
                )

        phrase.rhythm_pattern = " ".join(rhythm_symbols)
        annotations.append(
            annotation(
                "rhythm",
                phrase.start_word,
                phrase.end_word,
                "标准强弱节奏",
                phrase.rhythm_pattern,
                0.86,
                evidence={"source": "cmudict+sentence-stress-rules"},
            )
        )
        tone_name, tone_symbol, tone_confidence = suggested_tone(
            phrase, words, phrase_index == len(phrases) - 1
        )
        phrase.intonation = tone_name
        phrase.intonation_symbol = tone_symbol
        phrase.confidence = tone_confidence
        annotations.append(
            annotation(
                "intonation",
                phrase.start_word,
                phrase.end_word,
                tone_name,
                tone_symbol,
                tone_confidence,
                evidence={"source": "sentence-type-rule", "not_observed_audio": True},
            )
        )
        pause_symbol = "//" if phrase_index == len(phrases) - 1 or any(
            mark in words[phrase.end_word].punctuation_after for mark in ".!?"
        ) else "/"
        annotations.append(
            annotation(
                "pause" if phrase_index < len(phrases) - 1 else "phrase_boundary",
                phrase.end_word,
                phrase.end_word,
                "标准长停顿" if pause_symbol == "//" else "标准短停顿",
                pause_symbol,
                0.9,
                evidence={"source": "punctuation+phrase-rule", "recommended_pause_ms": 520 if pause_symbol == "//" else 280},
            )
        )

    for index, current in enumerate(words[:-1]):
        following = words[index + 1]
        if current.punctuation_after:
            continue
        final = final_letter(current.text)
        initial = initial_letter(following.text)
        if final and initial and ((final not in VOWELS and initial in VOWELS) or (final in VOWELS and initial in VOWELS)):
            annotations.append(
                annotation(
                    "linking",
                    index,
                    index + 1,
                    "标准自然朗读连读建议",
                    "‿",
                    0.74,
                    evidence={"source": "cross-word-sound-environment", "not_observed_audio": True},
                )
            )
        if final in STOP_CONSONANTS and initial and initial not in VOWELS:
            annotations.append(
                annotation(
                    "unreleased_stop",
                    index,
                    index,
                    f"自然朗读中词尾 /{final}/ 可不完全释放",
                    f"{final}̚",
                    0.68,
                    experimental=True,
                    evidence={"source": "stop-before-consonant-rule", "not_observed_audio": True},
                )
            )

    annotations.sort(key=lambda item: (item.start_word, item.end_word, item.type))
    counts = Counter(item.type for item in annotations)
    total_syllables = sum(word.syllables for word in words)
    estimated_duration = words[-1].end if words else 0
    summary = {
        "counts": dict(counts),
        "rhythm": {
            "syllables": total_syllables,
            "syllables_per_second": round(total_syllables / max(0.1, estimated_duration), 2),
            "mean_stress_interval": None,
            "stress_intervals": [],
        },
        "word_count": len(words),
        "phrase_count": len(phrases),
        "duration_seconds": round(estimated_duration, 2),
        "transcript_source": "text-standard",
        "input_mode": "text",
        "experimental_notice": "这是标准朗读建议，不是对真实音频的检测结果。",
    }
    return phrases, annotations, summary


def build_standard_reading(job_id: str, transcript: str, accent: str) -> AnalysisResult:
    normalized = normalize_transcript(transcript)
    words = make_standard_words(normalized)
    phrases, annotations, summary = analyze_standard_text(words)
    return AnalysisResult(
        version=__version__,
        job_id=job_id,
        created_at=utc_now(),
        accent=accent,
        input_mode="text",
        transcript=normalized,
        transcript_source="text-standard",
        alignment_quality=0.0,
        audio=None,
        words=words,
        phrases=phrases,
        annotations=annotations,
        contours={"times": [], "f0_hz": [], "intensity_db": []},
        summary=summary,
        limitations=[
            "当前结果根据标准发音词典、句型和自然朗读规则生成，不代表某位说话人的实际发音。",
            "上下文强调会改变句子重音；如需分析实际处理方式，请使用音频分析模式。",
            "连读和失爆是标准自然朗读建议，不要求朗读者在所有场景中强制使用。",
        ],
    )
