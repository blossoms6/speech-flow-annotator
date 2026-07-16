from app.text_standard import build_standard_reading, pronunciation_for


def test_cmudict_places_lexical_stress() -> None:
    _pronunciation, about_stress = pronunciation_for("about")
    _pronunciation, previous_stress = pronunciation_for("previous")
    assert about_stress == [0, 1]
    assert 1 in previous_stress


def test_standard_reading_has_word_aligned_rhythm() -> None:
    result = build_standard_reading(
        "textjob",
        "What do we learn from previous studies about anxiety?",
        "general-american",
    )
    phrase = result.phrases[0]
    beat_count = len(phrase.rhythm_pattern.split())
    syllable_count = sum(word.syllables for word in result.words)
    assert beat_count == syllable_count
    assert result.input_mode == "text"
    assert result.audio is None
    assert any(item.type == "weak_form" for item in result.annotations)
    assert any(item.type == "prominence" for item in result.annotations)
