from __future__ import annotations

import difflib
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from app.audio import AcousticFeatures, AudioData
from app.schemas import Word
from app.text import TextToken, normalize_transcript, rebuild_transcript, syllable_count, tokenize_transcript


ProgressCallback = Callable[[int, str, str], None]


@dataclass
class TimedToken:
    text: str
    normalized: str
    start: float
    end: float
    confidence: float


@dataclass
class TranscriptResult:
    transcript: str
    source: str
    words: list[Word]
    alignment_quality: float


_MODEL_CACHE: dict[tuple[str, str], object] = {}
_MODEL_LOCK = threading.Lock()


def faster_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def transcribe_audio(
    audio_path: Path,
    model_name: str,
    device: str = "auto",
    progress: ProgressCallback | None = None,
) -> tuple[str, list[TimedToken]]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "尚未安装自动转写组件。请运行 install-transcription.ps1，或在上传时提供英文原文。"
        ) from exc

    selected_device = device
    if device == "auto":
        selected_device = "cpu"
        try:
            import torch

            if torch.cuda.is_available():
                selected_device = "cuda"
        except ImportError:
            pass
    compute_type = "float16" if selected_device == "cuda" else "int8"
    cache_key = (model_name, selected_device)
    with _MODEL_LOCK:
        model = _MODEL_CACHE.get(cache_key)
        if model is None:
            if progress:
                progress(18, "loading_model", f"正在加载 {model_name} 转写模型，首次使用需要下载。")
            try:
                model = WhisperModel(model_name, device=selected_device, compute_type=compute_type)
            except Exception:
                if selected_device != "cuda":
                    raise
                selected_device = "cpu"
                cache_key = (model_name, selected_device)
                model = _MODEL_CACHE.get(cache_key)
                if model is None:
                    model = WhisperModel(model_name, device="cpu", compute_type="int8")
            _MODEL_CACHE[cache_key] = model

    if progress:
        progress(24, "transcribing", "正在进行英文转写并生成逐词时间戳。")
    segments, _info = model.transcribe(
        str(audio_path),
        language="en",
        beam_size=5,
        vad_filter=True,
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    timed: list[TimedToken] = []
    segment_text: list[str] = []
    for segment in segments:
        segment_text.append(segment.text.strip())
        for item in segment.words or []:
            tokens = tokenize_transcript(item.word)
            if not tokens:
                continue
            token = tokens[0]
            timed.append(
                TimedToken(
                    text=token.text,
                    normalized=token.normalized,
                    start=max(0.0, float(item.start)),
                    end=max(float(item.start), float(item.end)),
                    confidence=float(getattr(item, "probability", 0.7) or 0.7),
                )
            )
    transcript = normalize_transcript(" ".join(segment_text))
    return transcript, timed


def _speech_intervals(features: AcousticFeatures, duration: float) -> list[tuple[float, float]]:
    mask = features.speech_mask
    times = features.times
    if not len(mask) or not np.any(mask):
        return [(0.0, duration)]
    indices = np.flatnonzero(mask)
    intervals: list[list[float]] = []
    start = float(times[indices[0]] - 0.02)
    previous = indices[0]
    for index in indices[1:]:
        if index - previous > 7:
            intervals.append([max(0.0, start), min(duration, float(times[previous] + 0.02))])
            start = float(times[index] - 0.02)
        previous = index
    intervals.append([max(0.0, start), min(duration, float(times[previous] + 0.02))])
    return [(start, end) for start, end in intervals if end > start]


def _active_to_time(position: float, intervals: list[tuple[float, float]]) -> float:
    remaining = max(0.0, position)
    for start, end in intervals:
        length = end - start
        if remaining <= length:
            return start + remaining
        remaining -= length
    return intervals[-1][1]


def estimate_words_from_text(
    transcript: str,
    audio: AudioData,
    features: AcousticFeatures,
    confidence: float = 0.36,
) -> list[Word]:
    tokens = tokenize_transcript(transcript)
    if not tokens:
        raise ValueError("没有检测到可分析的英文单词。")
    intervals = _speech_intervals(features, audio.duration)
    active_duration = sum(end - start for start, end in intervals)
    weights = np.array([max(1.0, syllable_count(token.text) * 1.15 + len(token.text) * 0.08) for token in tokens])
    boundaries = np.concatenate(([0.0], np.cumsum(weights) / np.sum(weights) * active_duration))
    result: list[Word] = []
    for index, token in enumerate(tokens):
        start = _active_to_time(float(boundaries[index]), intervals)
        end = _active_to_time(float(boundaries[index + 1]), intervals)
        result.append(
            Word(
                index=index,
                text=token.text,
                normalized=token.normalized,
                punctuation_after=token.punctuation_after,
                start=round(start, 3),
                end=round(max(start + 0.03, end), 3),
                confidence=confidence,
                alignment_method="energy-estimated",
                syllables=syllable_count(token.text),
            )
        )
    return result


def _distribute_tokens(
    tokens: list[TextToken],
    start: float,
    end: float,
    confidence: float,
    method: str,
    offset: int,
) -> list[Word]:
    if not tokens:
        return []
    usable_end = max(start + 0.04 * len(tokens), end)
    weights = np.array([max(1.0, syllable_count(token.text)) for token in tokens], dtype=float)
    boundaries = np.concatenate(([0.0], np.cumsum(weights) / np.sum(weights)))
    result: list[Word] = []
    for local_index, token in enumerate(tokens):
        word_start = start + float(boundaries[local_index]) * (usable_end - start)
        word_end = start + float(boundaries[local_index + 1]) * (usable_end - start)
        result.append(
            Word(
                index=offset + local_index,
                text=token.text,
                normalized=token.normalized,
                punctuation_after=token.punctuation_after,
                start=round(word_start, 3),
                end=round(word_end, 3),
                confidence=confidence,
                alignment_method=method,
                syllables=syllable_count(token.text),
            )
        )
    return result


def align_reference_to_asr(reference: str, asr_words: list[TimedToken], duration: float) -> list[Word]:
    target = tokenize_transcript(reference)
    if not target:
        raise ValueError("提供的原文中没有可识别的英文单词。")
    source_norm = [word.normalized for word in asr_words]
    target_norm = [word.normalized for word in target]
    matcher = difflib.SequenceMatcher(a=source_norm, b=target_norm, autojunk=False)
    output: list[Word] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        target_slice = target[j1:j2]
        if tag == "equal":
            for source, token in zip(asr_words[i1:i2], target_slice):
                output.append(
                    Word(
                        index=len(output),
                        text=token.text,
                        normalized=token.normalized,
                        punctuation_after=token.punctuation_after,
                        start=round(source.start, 3),
                        end=round(source.end, 3),
                        confidence=round(source.confidence, 3),
                        alignment_method="whisper-matched",
                        syllables=syllable_count(token.text),
                    )
                )
            continue

        if not target_slice:
            continue
        previous_end = output[-1].end if output else 0.0
        next_start = asr_words[i2].start if i2 < len(asr_words) else duration
        if i2 > i1:
            start = asr_words[i1].start
            end = asr_words[i2 - 1].end
            confidence = float(np.mean([item.confidence for item in asr_words[i1:i2]])) * 0.7
            method = "whisper-reconciled"
        else:
            start = previous_end
            end = max(start + 0.08 * len(target_slice), next_start)
            confidence = 0.38
            method = "interpolated"
        output.extend(_distribute_tokens(target_slice, start, end, confidence, method, len(output)))

    for index, word in enumerate(output):
        word.index = index
        if index and word.start < output[index - 1].end:
            midpoint = (word.start + output[index - 1].end) / 2
            output[index - 1].end = round(midpoint, 3)
            word.start = round(midpoint, 3)
    return output


def transcript_match_score(reference: str, asr_words: list[TimedToken]) -> float:
    """Measure how much of the shorter text is supported by Whisper word order."""
    reference_words = [token.normalized for token in tokenize_transcript(reference)]
    recognized_words = [word.normalized for word in asr_words]
    if not reference_words or not recognized_words:
        return 0.0
    if min(len(reference_words), len(recognized_words)) < 4:
        return 1.0
    matcher = difflib.SequenceMatcher(a=recognized_words, b=reference_words, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    coverage = matched / min(len(reference_words), len(recognized_words))
    return round(max(matcher.ratio(), coverage), 3)


def build_transcript_result(
    audio: AudioData,
    features: AcousticFeatures,
    supplied_transcript: str,
    auto_transcribe: bool,
    model_name: str,
    device: str,
    progress: ProgressCallback | None = None,
) -> TranscriptResult:
    supplied = normalize_transcript(supplied_transcript)
    asr_text = ""
    asr_words: list[TimedToken] = []
    rejected_reference = False

    if auto_transcribe:
        asr_text, asr_words = transcribe_audio(audio.path, model_name, device, progress)

    if supplied and asr_words:
        match_score = transcript_match_score(supplied, asr_words)
        if match_score >= 0.35:
            words = align_reference_to_asr(supplied, asr_words, audio.duration)
            quality = float(np.mean([word.confidence for word in words])) if words else 0.0
            return TranscriptResult(supplied, "user+whisper", words, round(quality, 3))
        rejected_reference = True
    if asr_words:
        tokens = tokenize_transcript(asr_text)
        # Whisper punctuation is reconstructed from segment text; timings come from ASR tokens.
        if len(tokens) == len(asr_words):
            words = [
                Word(
                    index=index,
                    text=token.text,
                    normalized=token.normalized,
                    punctuation_after=token.punctuation_after,
                    start=round(timed.start, 3),
                    end=round(timed.end, 3),
                    confidence=round(timed.confidence, 3),
                    alignment_method="whisper",
                    syllables=syllable_count(token.text),
                )
                for index, (token, timed) in enumerate(zip(tokens, asr_words))
            ]
        else:
            words = align_reference_to_asr(asr_text, asr_words, audio.duration)
        transcript = rebuild_transcript(
            [TextToken(word.text, word.normalized, word.punctuation_after) for word in words]
        )
        quality = float(np.mean([word.confidence for word in words])) if words else 0.0
        source = "whisper-reference-mismatch" if rejected_reference else "whisper"
        return TranscriptResult(transcript, source, words, round(quality, 3))
    if supplied:
        words = estimate_words_from_text(supplied, audio, features)
        return TranscriptResult(supplied, "user-estimated", words, 0.36)
    raise ValueError("请提供英文原文，或启用并安装自动转写组件。")
