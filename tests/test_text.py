from app.text import normalize_transcript, syllable_count, tokenize_transcript


def test_tokenize_attaches_punctuation() -> None:
    tokens = tokenize_transcript("I don't know, but we'll try.")
    assert [token.text for token in tokens] == ["I", "don't", "know", "but", "we'll", "try"]
    assert tokens[2].punctuation_after == ","
    assert tokens[-1].punctuation_after == "."


def test_normalize_and_syllables() -> None:
    assert normalize_transcript("  We’re   ready. ") == "We're ready."
    assert syllable_count("project") == 2
    assert syllable_count("the") == 1
