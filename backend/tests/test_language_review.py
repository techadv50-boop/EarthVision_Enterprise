"""Local academic English checker used by the English review wing."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from app.services.language_review import review_document, review_local


def _docx(*texts: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in texts)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buf.getvalue()


def test_local_checker_flags_slang_broken_and_filler():
    paragraphs = [
        "Introduction",
        "This paper gonna show that the kids used a lot of stuff in the field.",
        "Because the sensors failed and",
        "In order to estimate yield we used Sentinel-2.",
        "This is unclear.",
        "References",
        "[1] Smith, J. (2020). Groundwater mapping with sensors. IJIST.",
    ]
    issues = review_local(paragraphs)
    cats = {item["category"] for item in issues}
    quotes = " ".join(item["quote"].lower() for item in issues)
    assert "slang" in cats
    assert "gonna" in quotes or "kids" in quotes or "stuff" in quotes or "a lot of" in quotes
    assert "broken_sentence" in cats or "sentence_structure" in cats
    assert "conciseness" in cats or "irrelevant_word" in cats
    assert not any(item["paragraph_index"] == 6 for item in issues)


def test_local_checker_flags_spelling_and_article():
    issues = review_local(
        [
            "The recieve of an sample was seperate from the control.",
        ]
    )
    cats = {item["category"] for item in issues}
    quotes = " ".join(item["quote"].lower() for item in issues)
    assert "spelling" in cats
    assert "recieve" in quotes or "seperate" in quotes
    assert "grammar" in cats


async def test_review_document_returns_highlighted_payload():
    data = _docx(
        "Introduction",
        "The team kinda measured runoff and the results were cool.",
        "Materials and Methods",
        "Plots were irrigated twice each week.",
    )
    result = await review_document(data, "draft.docx")
    assert result["filename"] == "draft.docx"
    assert result["engine"] in {"local", "openai"}
    assert result["paragraphs"]
    assert result["summary"]["issue_count"] == len(result["issues"])
    assert any(issue["category"] == "slang" for issue in result["issues"])
    flagged = [p for p in result["paragraphs"] if p["issue_ids"]]
    assert flagged
    assert all(isinstance(i, int) for p in flagged for i in p["issue_ids"])
