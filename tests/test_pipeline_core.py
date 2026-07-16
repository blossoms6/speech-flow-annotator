from pathlib import Path

from app.analyzers import run_all_analyzers
from app.audio import analyze_audio_quality, attach_word_acoustics, extract_acoustic_features, load_wav
from app.exports import render_markdown, render_srt
from app.transcription import estimate_words_from_text


def test_audio_features_and_quality(synthetic_wav: Path) -> None:
    audio = load_wav(synthetic_wav)
    features = extract_acoustic_features(audio)
    quality = analyze_audio_quality(audio, synthetic_wav.name, features)
    assert 3.0 < audio.duration < 3.3
    assert len(features.times) > 100
    assert quality.sample_rate == 16000
    assert quality.speech_ratio > 0.2
    assert max(features.f0_hz) > 100


def test_analysis_generates_structured_annotations(synthetic_wav: Path) -> None:
    audio = load_wav(synthetic_wav)
    features = extract_acoustic_features(audio)
    transcript = "We really need it, but we can finish it today."
    words = estimate_words_from_text(transcript, audio, features)
    attach_word_acoustics(words, features)
    phrases, annotations, summary = run_all_analyzers(words, features, audio)
    types = {item.type for item in annotations}
    assert len(words) == 10
    assert phrases
    assert "prominence" in types
    assert "rhythm" in types
    assert "intonation" in types
    assert "weak_form" in types
    assert summary["rhythm"]["syllables_per_second"] > 0


def test_exports_are_readable(synthetic_wav: Path) -> None:
    audio = load_wav(synthetic_wav)
    features = extract_acoustic_features(audio)
    words = estimate_words_from_text("We can finish it today.", audio, features)
    attach_word_acoustics(words, features)
    phrases, annotations, summary = run_all_analyzers(words, features, audio)
    result = {
        "audio": {"original_name": "sample.wav", "duration": audio.duration},
        "alignment_quality": 0.36,
        "words": [word.model_dump() for word in words],
        "phrases": [phrase.model_dump() for phrase in phrases],
        "annotations": [item.model_dump() for item in annotations],
        "summary": summary,
    }
    markdown = render_markdown(result)
    srt = render_srt(result)
    assert "英语语流分析稿" in markdown
    assert "-->" in srt
