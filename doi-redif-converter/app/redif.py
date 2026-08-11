"""Generate ReDIF-Article 1.0 files matching IJIST / RePEc conventions."""

from __future__ import annotations

import re

from .models import ArticleMeta

MONTHS = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}

# Default RePEc series for International Journal of Innovations in Science and Technology
DEFAULT_REPEC_HANDLE_PREFIX = "RePEc:abq:IJIST1"


def month_name(value: str | int | None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, int):
        return MONTHS.get(value, "")
    text = str(value).strip()
    if text.isdigit():
        return MONTHS.get(int(text), "")
    # already a month name
    for name in MONTHS.values():
        if text.lower() == name.lower():
            return name
    return text


def normalize_doi_url(doi: str) -> str:
    doi = doi.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    return f"https://doi.org/{doi}"


def build_filename(meta: ArticleMeta) -> str:
    """Build filename like V8i3p1429-1448.redif."""
    volume = (meta.volume or "0").strip()
    issue = (meta.issue or "0").strip()
    pages = (meta.pages or "0").strip().replace(" ", "")
    if not pages:
        # fall back to DOI suffix
        suffix = meta.doi.rstrip("/").split("/")[-1]
        pages = re.sub(r"[^A-Za-z0-9_-]+", "-", suffix) or "unknown"
    return f"V{volume}i{issue}p{pages}.redif"


def build_handle(meta: ArticleMeta, handle_prefix: str = DEFAULT_REPEC_HANDLE_PREFIX) -> str:
    volume = (meta.volume or "").strip()
    issue = (meta.issue or "").strip()
    year = (meta.year or "").strip()
    pages = (meta.pages or "").strip().replace(" ", "")
    return f"{handle_prefix}:v:{volume}:y:{year}:i:{issue}:p:{pages}"


def _line(key: str, value: str, spaced: bool = False) -> str:
    if value is None:
        value = ""
    value = str(value).replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()
    sep = ": " if spaced else ":"
    return f"{key}{sep}{value}"


def to_redif(meta: ArticleMeta, handle_prefix: str = DEFAULT_REPEC_HANDLE_PREFIX) -> str:
    """Serialize article metadata to ReDIF-Article 1.0 text (CRLF)."""
    lines: list[str] = [_line("Template-Type", "ReDIF-Article 1.0", spaced=True)]

    for author in meta.authors:
        if not author.name:
            continue
        lines.append(_line("Author-Name", author.name))
        if author.email:
            lines.append(_line("Author-Email", author.email))
        if author.workplace:
            lines.append(_line("Author-Workplace-Name", author.workplace))

    lines.append(_line("Title", meta.title))
    if meta.abstract:
        lines.append(_line("Abstract", meta.abstract))
    if meta.keywords:
        lines.append(_line("Keywords", ", ".join(meta.keywords)))
    if meta.journal:
        lines.append(_line("Journal", meta.journal))
    if meta.pages:
        lines.append(_line("Pages", meta.pages))
    if meta.volume:
        lines.append(_line("Volume", meta.volume))
    if meta.issue:
        lines.append(_line("Issue", meta.issue))
    if meta.year:
        lines.append(_line("Year", meta.year))
    if meta.month:
        lines.append(_line("Month", month_name(meta.month)))

    lines.append(_line("DOI", normalize_doi_url(meta.doi)))

    for link in meta.file_links:
        lines.append(_line("File-URL", link.url))
        # Sample uses a leading space after colon for File-Format
        lines.append(_line("File-Format", link.format, spaced=True))

    lines.append(_line("Handle", build_handle(meta, handle_prefix), spaced=True))

    return "\r\n".join(lines) + "\r\n"
