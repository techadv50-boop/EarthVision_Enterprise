"""Phone number extraction with multi-region support."""

from __future__ import annotations

import re
from pathlib import Path

import phonenumbers

from webcrawler.extractors.email import (
    _docx_text,
    _pdf_text,
    _xlsx_text,
)

# Loose pattern for candidates; phonenumbers + local rules validate.
PHONE_CANDIDATE_RE = re.compile(
    r"(?:\+|00)?(?:\d[\d\s()./-]{5,18}\d)",
)

# Common Pakistan formats that may fail default-region parsing.
PK_MOBILE_RE = re.compile(r"(?<!\d)(?:0?3\d{2}[-\s]?\d{7})(?!\d)")
PK_LANDLINE_RE = re.compile(r"(?<!\d)(?:0?5\d[-\s]?\d{7,8})(?!\d)")
TEL_HREF_RE = re.compile(r"tel:\s*([+\d][\d\s()./-]{5,})", re.IGNORECASE)

DEFAULT_REGIONS = ("PK", "US", "GB", "IN", "AE", "SA", "CA", "AU")


def region_from_url(url: str) -> str:
    host = (url or "").lower()
    if host.endswith(".pk") or ".pk/" in host or "qau.edu.pk" in host:
        return "PK"
    if host.endswith(".uk") or ".ac.uk" in host:
        return "GB"
    if host.endswith(".in") or ".ac.in" in host:
        return "IN"
    if host.endswith(".ae"):
        return "AE"
    if host.endswith(".sa"):
        return "SA"
    if host.endswith(".au"):
        return "AU"
    return "US"


def _normalize_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _format_parsed(parsed: phonenumbers.PhoneNumber) -> str:
    return phonenumbers.format_number(
        parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
    )


def _try_parse(candidate: str, regions: list[str]) -> str | None:
    for region in regions:
        try:
            parsed = phonenumbers.parse(candidate, region)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_possible_number(parsed) and phonenumbers.is_valid_number(parsed):
            return _format_parsed(parsed)
    return None


def _pk_fallback(candidate: str) -> str | None:
    digits = _normalize_digits(candidate)
    if candidate.strip().startswith("+"):
        if digits.startswith("92") and len(digits) in {12, 13}:
            return "+" + digits
    # Mobile 03XX-XXXXXXX -> +92 3XX XXXXXXX
    if len(digits) == 11 and digits.startswith("03"):
        return "+92" + digits[1:]
    if len(digits) == 10 and digits.startswith("3"):
        return "+92" + digits
    # Landline 051-XXXXXXX
    if len(digits) == 10 and digits.startswith("0"):
        return "+92" + digits[1:]
    if len(digits) == 11 and digits.startswith("92"):
        return "+" + digits
    return None


def extract_phones_from_text(
    text: str,
    default_region: str = "US",
    regions: list[str] | None = None,
) -> set[str]:
    found: set[str] = set()
    if not text:
        return found

    region_order: list[str] = []
    for region in [default_region, *(regions or DEFAULT_REGIONS)]:
        if region and region not in region_order:
            region_order.append(region)

    candidates: list[str] = []
    candidates.extend(PHONE_CANDIDATE_RE.findall(text))
    candidates.extend(PK_MOBILE_RE.findall(text))
    candidates.extend(PK_LANDLINE_RE.findall(text))
    candidates.extend(TEL_HREF_RE.findall(text))

    for candidate in candidates:
        candidate = candidate.strip().rstrip(".,;")
        digits = _normalize_digits(candidate)
        if len(digits) < 7 or len(digits) > 15:
            continue

        parsed = _try_parse(candidate, region_order)
        if parsed:
            found.add(parsed)
            continue

        # International with + / 00 prefix
        if candidate.startswith("+") or candidate.startswith("00"):
            if candidate.startswith("00"):
                digits = digits[2:] if digits.startswith("00") else digits
                found.add("+" + digits)
            else:
                found.add("+" + digits)
            continue

        pk = _pk_fallback(candidate)
        if pk and default_region == "PK":
            # Prefer structured parse when possible
            parsed_pk = _try_parse(pk, ["PK"])
            found.add(parsed_pk or pk)
            continue
        if pk and ("51" in digits or digits.startswith("03") or digits.startswith("3")):
            parsed_pk = _try_parse(pk, ["PK"])
            found.add(parsed_pk or pk)

    return found


def extract_phones_from_file(
    path: Path,
    default_region: str = "US",
    regions: list[str] | None = None,
) -> set[str]:
    suffix = path.suffix.lower()
    text = ""
    try:
        if suffix == ".eml":
            from webcrawler.scanner.folder_scanner import _eml_text

            text = _eml_text(path)
        elif suffix in {".html", ".htm", ".txt", ".csv", ".xml"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
        elif suffix == ".pdf":
            text = _pdf_text(path)
        elif suffix == ".docx":
            text = _docx_text(path)
        elif suffix in {".xlsx", ".xlsm"}:
            text = _xlsx_text(path)
    except Exception:
        return set()
    return extract_phones_from_text(text, default_region=default_region, regions=regions)
