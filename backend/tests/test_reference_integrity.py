"""Reference-section integrity: shuffle is OK when numbers stay on the same works."""

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


def test_shuffle_same_numbers_passes():
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
    assert result["status"] == "pass"
    assert result["order_changed"] is True
    assert result["removed"] == []
    assert result["added"] == []
    assert result["changed"] == []
    assert result["renumbered"] == []
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
    assert result["removed"][0]["original"]["number"] == 2


def test_added_reference_fails():
    extra = "[4] New, P. (2026). An extra paper. Nature."
    original = _docx(*ORIGINAL)
    returned = _docx(*ORIGINAL, extra)
    result = compare_manuscripts(original, returned)
    assert result["status"] == "fail"
    assert len(result["added"]) == 1
    assert result["added"][0]["returned"]["number"] == 4


def test_changed_reference_fails():
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
    assert len(result["changed"]) == 1
    assert result["changed"][0]["original"]["number"] == 3


def test_renumbered_reference_fails():
    original = _docx(*ORIGINAL)
    returned = _docx(
        "References",
        "[1] Smith, J. (2020). Groundwater mapping with sensors. IJIST, Vol. 4 Issue. 1 pp 10-18.",
        "[2] Ali, B. (2022). Crop yield from Sentinel-2. IJIST, Vol. 6 Issue. 3 pp 30-41, doi:10.33411/IJIST/20220603001.",
        "[3] Khan, A. (2021). Urban heat islands in arid basins. IJIST, Vol. 5 Issue. 2 pp 20-28.",
    )
    result = compare_manuscripts(original, returned)
    assert result["status"] == "fail"
    assert result["renumbered"] or result["changed"]


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
    assert result["order_changed"] is False
    assert result["unchanged_count"] == 3
