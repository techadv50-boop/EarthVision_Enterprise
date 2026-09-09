"""Extract manuscript text from PDF, Word (.docx), and plain text uploads."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from lxml import etree

from app.services.pdf_text import extract_pdf_text

W_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def extract_manuscript_text(data: bytes, filename: str = "") -> str:
    name = (filename or "").lower()
    if data[:4] == b"%PDF" or name.endswith(".pdf"):
        text, _status = extract_pdf_text(data)
        if text.strip():
            return text
    if data[:2] == b"PK" or name.endswith(".docx"):
        text = extract_docx_text(data)
        if text.strip():
            return text
    if name.endswith((".txt", ".md")) or _looks_like_text(data):
        return _decode_text(data)
    return ""


def paragraph_text(para) -> str:
    """Visible paragraph text, ignoring tracked inserts and note references."""
    pieces: list[str] = []
    for node in para.findall(".//w:t", W_NS):
        skip = False
        parent = node.getparent()
        while parent is not None:
            tag = etree.QName(parent).localname
            if tag in {"ins", "del", "endnoteReference", "footnoteReference", "commentReference"}:
                skip = True
                break
            parent = parent.getparent()
        if skip:
            continue
        pieces.append(node.text or "")
    return re.sub(r"\s+", " ", "".join(pieces)).strip()


def extract_docx_paragraphs(data: bytes) -> list[str]:
    """Return each non-empty Word paragraph, in document order."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
    except Exception:
        return []
    try:
        root = etree.fromstring(xml)
    except Exception:
        return []
    paragraphs: list[str] = []
    for para in root.findall(".//w:p", W_NS):
        line = paragraph_text(para)
        if line:
            paragraphs.append(line)
    return paragraphs


def _inside_tags(node, tags: set[str]) -> bool:
    parent = node.getparent()
    while parent is not None:
        if etree.QName(parent).localname in tags:
            return True
        parent = parent.getparent()
    return False


def _list_num_id(para) -> str | None:
    p_pr = para.find("w:pPr", W_NS)
    if p_pr is None:
        return None
    num_pr = p_pr.find("w:numPr", W_NS)
    if num_pr is None:
        return None
    num_id = num_pr.find("w:numId", W_NS)
    if num_id is None:
        return None
    value = num_id.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")
    return value or None


def review_paragraph_text(para) -> str:
    """Visible paragraph text for operator review: keep insertions, drop deletions.

    Line breaks inside a paragraph are preserved so bibliography entries that
    staff separated with Shift+Enter are not glued into one reference.
    """
    pieces: list[str] = []
    for node in para.iter():
        try:
            tag = etree.QName(node).localname
        except Exception:
            continue
        if tag in {"br", "cr"}:
            if not _inside_tags(node, {"del", "endnoteReference", "footnoteReference", "commentReference"}):
                pieces.append("\n")
            continue
        if tag == "tab":
            pieces.append("\t")
            continue
        if tag != "t":
            continue
        if _inside_tags(node, {"del", "endnoteReference", "footnoteReference", "commentReference"}):
            continue
        pieces.append(node.text or "")
    text = "".join(pieces)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def extract_review_paragraphs(data: bytes) -> list[str]:
    """Paragraphs for Reference check / English review, including Word list numbers."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
    except Exception:
        return []
    try:
        root = etree.fromstring(xml)
    except Exception:
        return []
    counters: dict[str, int] = {}
    paragraphs: list[str] = []
    for para in root.findall(".//w:p", W_NS):
        line = review_paragraph_text(para)
        num_id = _list_num_id(para)
        if num_id:
            counters[num_id] = counters.get(num_id, 0) + 1
            n = counters[num_id]
            stripped = line.lstrip()
            if stripped and not re.match(r"^(\[\d+\]|\(\d+\)|\d{1,3}[\.\)])\s", stripped):
                line = f"[{n}] {stripped}" if stripped else f"[{n}]"
        if line:
            paragraphs.append(line)
    return paragraphs


def extract_docx_text(data: bytes) -> str:
    return "\n\n".join(extract_docx_paragraphs(data))


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            text = data.decode(encoding)
        except Exception:
            continue
        if text.strip():
            return text
    return ""


def _looks_like_text(data: bytes) -> bool:
    sample = data[:800]
    if not sample:
        return False
    if b"\x00" in sample:
        return False
    printable = sum(32 <= byte < 127 or byte in b"\n\r\t" for byte in sample)
    return printable / max(1, len(sample)) >= 0.85


def suffix_for(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext in {".pdf", ".docx", ".doc", ".txt", ".md"}:
        return ext
    return ".bin"
