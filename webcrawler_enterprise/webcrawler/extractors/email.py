"""Email address extraction from text and documents."""

from __future__ import annotations

import re
from pathlib import Path

EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"(?![A-Za-z0-9._%+-])",
    re.IGNORECASE,
)

INVALID_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js"}


def extract_emails_from_text(text: str) -> set[str]:
    found: set[str] = set()
    for match in EMAIL_RE.findall(text or ""):
        email = match.strip().rstrip(".,;:)>]}'\"").lower()
        if any(email.endswith(suf) for suf in INVALID_SUFFIXES):
            continue
        if email.count("@") != 1:
            continue
        local, domain = email.split("@", 1)
        if not local or not domain or "." not in domain:
            continue
        found.add(email)
    return found


def extract_emails_from_file(path: Path) -> set[str]:
    suffix = path.suffix.lower()
    text = ""
    try:
        if suffix in {".html", ".htm", ".txt", ".csv"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
        elif suffix == ".pdf":
            text = _pdf_text(path)
        elif suffix == ".docx":
            text = _docx_text(path)
        elif suffix in {".xlsx", ".xlsm"}:
            text = _xlsx_text(path)
    except Exception:
        return set()
    return extract_emails_from_text(text)


def _pdf_text(path: Path) -> str:
    chunks: list[str] = []
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[:50]:
                chunks.append(page.extract_text() or "")
    except Exception:
        try:
            import fitz

            doc = fitz.open(path)
            for i, page in enumerate(doc):
                if i >= 50:
                    break
                chunks.append(page.get_text())
            doc.close()
        except Exception:
            return ""
    return "\n".join(chunks)


def _docx_text(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def _xlsx_text(path: Path) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    parts: list[str] = []
    for sheet in wb.worksheets:
        for row in sheet.iter_rows(max_row=500, values_only=True):
            for cell in row:
                if cell is not None:
                    parts.append(str(cell))
    wb.close()
    return "\n".join(parts)
