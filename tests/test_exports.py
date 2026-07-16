from __future__ import annotations

from app.exports import render_print_html
from app.text_standard import build_standard_reading


def test_print_html_keeps_words_and_rhythm_beats_in_cells() -> None:
    result = build_standard_reading(
        "pdf-test",
        "What do we learn from previous studies about anxiety?",
        "general-american",
    ).model_dump()

    document = render_print_html(result)

    assert "英语语流标注稿" in document
    assert document.count('class="rhythm-cell"') == len(result["words"])
    assert "What" in document
    assert "●" in document
    assert "PDF 为静态学习稿" in document
