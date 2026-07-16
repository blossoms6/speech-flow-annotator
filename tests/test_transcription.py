from __future__ import annotations

from app.transcription import TimedToken, transcript_match_score
from app.text import tokenize_transcript


def timed_words(text: str) -> list[TimedToken]:
    return [
        TimedToken(token.text, token.normalized, index * 0.3, index * 0.3 + 0.25, 0.9)
        for index, token in enumerate(tokenize_transcript(text))
    ]


def test_reference_match_accepts_a_supported_excerpt() -> None:
    recognized = timed_words(
        "Listen to the tape then answer the question. Pumas are large cat-like animals found in America."
    )

    assert transcript_match_score("Pumas are large cat-like animals found in America.", recognized) == 1.0


def test_reference_match_rejects_stale_unrelated_text() -> None:
    recognized = timed_words(
        "Pumas are large cat-like animals which are found in America and sometimes travel far."
    )
    stale = (
        "The aluminum alloy die forging process is conducted under complex operating conditions "
        "involving highly dynamic multi-physics field coupling."
    )

    assert transcript_match_score(stale, recognized) < 0.35
