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
    pieces = [node.text or "" for node in para.findall(".//w:t", W_NS)]
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
