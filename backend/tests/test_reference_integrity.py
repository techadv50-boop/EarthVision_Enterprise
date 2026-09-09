"""Reference-section integrity: split real bibliographies and classify edits."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from app.services.reference_integrity import (
    compare_manuscripts,
    parse_reference_items,
)


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


def _numbered_docx(*texts: str) -> bytes:
    """Word-style auto-numbered paragraphs (numbers live in numPr, not in the text)."""
    paras = []
    for text in texts:
        if text in {"References", "Introduction"}:
            paras.append(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>")
            continue
        paras.append(
            "<w:p><w:pPr><w:numPr><w:ilvl w:val=\"0\"/><w:numId w:val=\"1\"/></w:numPr></w:pPr>"
            f"<w:r><w:t>{escape(text)}</w:t></w:r></w:p>"
        )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(paras)}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buf.getvalue()


REF_A = "[1] Smith, J. (2020). Groundwater mapping with sensors. IJIST, Vol. 4 Issue. 1 pp 10-18."
REF_B = "[2] Khan, A. (2021). Urban heat islands in arid basins. IJIST, Vol. 5 Issue. 2 pp 20-28."
REF_C = "[3] Ali, B. (2022). Crop yield from Sentinel-2. IJIST, Vol. 6 Issue. 3 pp 30-41, doi:10.33411/IJIST/20220603001."

ORIGINAL = [
    "Introduction",
    "This study uses archive papers.",
    "References",
    REF_A,
    REF_B,
    REF_C,
]


def test_unnumbered_paragraphs_are_separate_references():
    items = parse_reference_items(
        [
            "Smith, J. (2020). Groundwater mapping with sensors. IJIST.",
            "Khan, A. (2021). Urban heat islands in arid basins. IJIST.",
            "Ali, B. (2022). Crop yield from Sentinel-2. IJIST.",
        ]
    )
    assert len(items) == 3
    assert items[0].number == 1
    assert "Khan" in items[1].body


def test_word_list_numbering_is_not_collapsed_to_one_item():
    original = _numbered_docx(
        "Introduction",
        "References",
        "Smith, J. (2020). Groundwater mapping with sensors. IJIST.",
        "Khan, A. (2021). Urban heat islands in arid basins. IJIST.",
        "Ali, B. (2022). Crop yield from Sentinel-2. IJIST.",
    )
    returned = _numbered_docx(
        "Introduction",
        "References",
        "Smith, J. (2020). Groundwater mapping with sensors. IJIST.",
        "Ali, B. (2022). Crop yield from Sentinel-2. IJIST.",
    )
    result = compare_manuscripts(original, returned)
    assert result["original_count"] == 3
    assert result["returned_count"] == 2
    assert result["status"] == "fail"
    assert len(result["removed"]) == 1
    assert "Khan" in (result["removed"][0]["original"]["text"] or "")


def test_shuffle_is_place_change_not_deletion():
    original = _docx(*ORIGINAL)
    returned = _docx(
        "Introduction",
        "This study uses archive papers.",
        "References",
        REF_C,
        REF_A,
        REF_B,
    )
    result = compare_manuscripts(original, returned)
    assert result["removed"] == []
    assert result["added"] == []
    assert result["amended"] == []
    assert result["place_changed"]
    assert result["overall"]["place_changed"] == len(result["place_changed"])
    assert result["status"] in {"pass", "warn"}
    assert result["original_count"] == 3
    assert result["returned_count"] == 3


def test_removed_reference_fails():
    original = _docx(*ORIGINAL)
    returned = _docx(
        "Introduction",
        "References",
        REF_A,
        REF_C,
    )
    result = compare_manuscripts(original, returned)
    assert result["status"] == "fail"
    assert len(result["removed"]) == 1
    assert result["overall"]["removed"] == 1
    assert result["removed"][0]["original"]["number"] == 2


def test_added_reference_fails():
    extra = "[4] New, P. (2026). An extra paper. Nature."
    original = _docx(*ORIGINAL)
    returned = _docx(*ORIGINAL, extra)
    result = compare_manuscripts(original, returned)
    assert result["status"] == "fail"
    assert len(result["added"]) == 1
    assert result["added"][0]["returned"]["number"] == 4


def test_amended_reference_fails():
    changed_c = "[3] Ali, B. (2022). Completely different title about bridges. Nature."
    original = _docx(*ORIGINAL)
    returned = _docx(
        "Introduction",
        "References",
        REF_A,
        REF_B,
        changed_c,
    )
    result = compare_manuscripts(original, returned)
    assert result["status"] == "fail"
    assert len(result["amended"]) == 1
    assert result["amended"][0]["original"]["number"] == 3


def test_style_only_is_not_treated_as_amended():
    original = _docx(*ORIGINAL)
    styled = "[1] Smith, J. (2020). Groundwater mapping with sensors. IJIST, Vol. 4 Issue. 1 pp 10-18"
    returned = _docx(
        "Introduction",
        "References",
        styled,
        REF_B,
        REF_C,
    )
    result = compare_manuscripts(original, returned)
    assert result["amended"] == []
    assert result["removed"] == []
    assert result["style_changed"] or result["status"] in {"pass", "warn"}


def test_parse_multiline_and_numbered_heading():
    items = parse_reference_items(
        [
            "[1] Smith, J. (2020). Groundwater mapping",
            "with sensors. IJIST.",
            "2. Khan, A. (2021). Urban heat islands in arid basins.",
        ]
    )
    assert len(items) == 2
    assert items[0].number == 1
    assert "with sensors" in items[0].body
    assert items[1].number == 2


def test_identical_files_pass():
    original = _docx(*ORIGINAL)
    result = compare_manuscripts(original, original, original_name="a.docx", returned_name="b.docx")
    assert result["status"] == "pass"
    assert result["place_changed"] == []
    assert result["unchanged_count"] == 3
    assert result["overall"]["unchanged"] == 3
