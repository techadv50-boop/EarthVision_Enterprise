"""Build an amended Word manuscript with accepted house citations."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape
from typing import Any, Iterable


def assign_citations(paragraphs: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Number accepted suggestions in reading order and append [n] markers."""
    refs: list[dict[str, Any]] = []
    seen: dict[int, int] = {}
    out: list[dict[str, Any]] = []
    for para in paragraphs:
        numbers: list[int] = []
        suggestions = []
        for sug in para.get("suggestions") or []:
            row = dict(sug)
            if row.get("status") == "accepted":
                article_id = int(row.get("article_id") or 0)
                if article_id not in seen:
                    seen[article_id] = len(refs) + 1
                    refs.append(
                        {
                            "number": seen[article_id],
                            "house_citation": row.get("house_citation") or row.get("reason") or "",
                            "article_id": article_id,
                            "title": ((row.get("article") or {}) or {}).get("title")
                            if isinstance(row.get("article"), dict)
                            else None,
                        }
                    )
                row["citation_number"] = seen[article_id]
                if seen[article_id] not in numbers:
                    numbers.append(seen[article_id])
            else:
                row["citation_number"] = None
            suggestions.append(row)
        marker = "".join(f"[{n}]" for n in numbers)
        text = (para.get("text") or "").rstrip()
        display = f"{text} {marker}".strip() if marker else text
        out.append(
            {
                **para,
                "suggestions": suggestions,
                "citation_numbers": numbers,
                "display_text": display,
            }
        )
    return out, refs


def build_amended_docx(
    *,
    title: str,
    paragraphs: list[dict[str, Any]],
    references: list[dict[str, Any]],
) -> bytes:
    body: list[str] = [_p(title, bold=True, size=32, space_after=360)]
    if not paragraphs:
        body.append(_p("(Empty manuscript)"))
    for para in paragraphs:
        body.append(_p(para.get("display_text") or para.get("text") or ""))
    if references:
        body.append(_p("References", bold=True, size=28, space_before=400, space_after=200))
        for ref in references:
            citation = ref.get("house_citation") or ""
            body.append(_p(f"[{ref['number']}] {citation}"))
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + "</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/document.xml", document)
    return buf.getvalue()


def _p(
    text: str,
    *,
    bold: bool = False,
    size: int = 24,
    space_after: int = 240,
    space_before: int = 0,
) -> str:
    rpr = f'<w:rPr><w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
    if bold:
        rpr += "<w:b/>"
    rpr += (
        '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>'
        "</w:rPr>"
    )
    spacing = f'<w:spacing w:after="{space_after}" w:before="{space_before}" w:line="276" w:lineRule="auto"/>'
    return (
        f"<w:p><w:pPr>{spacing}</w:pPr><w:r>{rpr}"
        f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
    )


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
