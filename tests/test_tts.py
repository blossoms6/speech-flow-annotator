from __future__ import annotations

from app.schemas import Word
from app.tts import apply_synthesis_boundaries


def test_apply_neural_word_boundaries_handles_hyphenated_words() -> None:
    words = [
        Word(index=0, text="We", normalized="we", start=0.0, end=0.3),
        Word(index=1, text="multi-physics", normalized="multi-physics", start=0.35, end=1.0),
        Word(index=2, text="models", normalized="models", start=1.05, end=1.5),
    ]
    boundaries = [
        {"text": "We", "start": 0.12, "end": 0.31},
        {"text": "multi", "start": 0.36, "end": 0.66},
        {"text": "physics", "start": 0.67, "end": 1.02},
        {"text": "models", "start": 1.09, "end": 1.48},
    ]

    quality = apply_synthesis_boundaries(words, boundaries, duration=1.7)

    assert quality == 1.0
    assert words[1].start == 0.36
    assert words[1].end == 1.02
    assert all(word.alignment_method == "neural-tts-word-boundary" for word in words)
