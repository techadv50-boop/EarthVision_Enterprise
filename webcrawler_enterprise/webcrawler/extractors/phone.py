"""Phone number extraction."""

from __future__ import annotations

import re
from pathlib import Path

import phonenumbers

from webcrawler.extractors.email import (
    _docx_text,
    _pdf_text,
    _xlsx_text,
)

# Loose pattern for candidates; phonenumbers validates.
PHONE_CANDIDATE_RE = re.compile(
    r"(?:\+|00)?[\d][\d\s()./-]{6,}\d",
)


def extract_phones_from_text(text: str, default_region: str = "US") -> set[str]:
    found: set[str] = set()
    if not text:
        return found
    for match in PHONE_CANDIDATE_RE.findall(text):
        candidate = match.strip()
        digits = re.sub(r"\D", "", candidate)
        if len(digits) < 7 or len(digits) > 15:
            continue
        try:
            parsed = phonenumbers.parse(candidate, default_region)
            if phonenumbers.is_possible_number(parsed) and phonenumbers.is_valid_number(parsed):
                formatted = phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
                )
                found.add(formatted)
                continue
        except phonenumbers.NumberParseException:
            pass
        # Keep reasonably formatted international-looking numbers even if region unknown.
        if candidate.startswith("+") and 8 <= len(digits) <= 15:
            found.add("+" + digits if not candidate.startswith("+") else candidate.replace(" ", ""))
    return found


def extract_phones_from_file(path: Path, default_region: str = "US") -> set[str]:
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
    return extract_phones_from_text(text, default_region=default_region)
