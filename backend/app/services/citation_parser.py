"""Parse IJIST galley first-page headers (Citation| / running Vol/Issue/Page)."""

from __future__ import annotations

import re
from typing import Any, Optional

MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
MONTH_RE = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"

RUNNING_HEADER_RE = re.compile(
    rf"(?P<month>{MONTH_RE})\s+(?P<year>\d{{4}})\s*\|\s*Vol\.?\s*(?P<volume>\d+)\s*\|\s*Issue\s*(?P<issue>\d+)",
    re.IGNORECASE,
)
PAGE_RE = re.compile(r"Page\s*\|\s*(?P<page>\d+)", re.IGNORECASE)
CITATION_RE = re.compile(
    r"Citation\|\s*(?P<authors>.+?),\s*[“\"\"](?P<title>.+?)[”\"\"]\s*,\s*IJIST,\s*"
    r"Vol\.\s*(?P<volume>\d+)\s*Issue\.\s*(?P<issue>\d+)\s*"
    r"pp\s*(?P<start>\d+)\s*-\s*(?P<end>\d+)\s*,\s*(?P<monthyear>[A-Za-z]+\s+\d{4})",
    re.IGNORECASE | re.DOTALL,
)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
DATE_FIELD_RE = re.compile(
    rf"(Received|Revised|Accepted|Published)\s*\|\s*({MONTH_RE}\.?\s+\d{{1,2}},?\s+\d{{4}}|{MONTH_RE}\.?\s+\d{{1,2}}\s+\d{{4}})",
    re.IGNORECASE,
)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n"))


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_authors(raw: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", raw).strip().rstrip(",")
    parts = re.split(r"\s*,\s*", cleaned)
    return [p.strip() for p in parts if p.strip()]


def extract_keywords(text: str) -> list[str]:
    match = re.search(r"Keywords\s*:\s*(.+?)(?:\n\n|\Z)", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    blob = collapse(match.group(1))
    blob = re.split(r"\n(?:Introduction|1\.|I\.)", blob, maxsplit=1)[0]
    items = re.split(r"[;•]", blob)
    return [i.strip(" .") for i in items if len(i.strip()) > 1][:40]


def extract_abstract(text: str) -> Optional[str]:
    collapsed_lines = normalize_whitespace(text)
    # After published date / keywords start.
    start = None
    pub = re.search(r"Published\s*\|[^\n]+\n", collapsed_lines, re.IGNORECASE)
    if pub:
        start = pub.end()
    else:
        rec = re.search(r"Received\s*\|", collapsed_lines, re.IGNORECASE)
        if rec:
            # skip the date line
            nl = collapsed_lines.find("\n", rec.start())
            start = nl + 1 if nl != -1 else rec.end()
    if start is None:
        return None
    rest = collapsed_lines[start:]
    kw = re.search(r"\nKeywords\s*:", rest, re.IGNORECASE)
    body = rest[: kw.start()] if kw else rest[:2500]
    body = re.sub(r"^\s*T\s*\n", "", body)  # stray dropped capital from some galleys
    body = collapse(body)
    return body[:4000] if body else None


def parse_ijist_header(text: str) -> dict[str, Any]:
    """Extract bibliographic fields from an IJIST galley first page (or full PDF text)."""
    raw = text or ""
    first = "\n".join(raw.splitlines()[:80])
    collapsed_first = collapse(first)
    collapsed_all = collapse(raw[:8000])

    result: dict[str, Any] = {
        "journal_name": "International Journal of Innovations in Science & Technology",
        "abbreviation": "IJIST",
        "title": None,
        "authors": [],
        "affiliations": [],
        "correspondence_email": None,
        "citation_raw": None,
        "volume": None,
        "issue": None,
        "page_start": None,
        "page_end": None,
        "month": None,
        "year": None,
        "received_date": None,
        "revised_date": None,
        "accepted_date": None,
        "published_date": None,
        "keywords": [],
        "abstract": None,
        "doi": None,
        "header_raw": first[:4000],
    }

    run = RUNNING_HEADER_RE.search(first) or RUNNING_HEADER_RE.search(collapsed_all)
    if run:
        result["month"] = run.group("month")
        result["year"] = int(run.group("year"))
        result["volume"] = int(run.group("volume"))
        result["issue"] = int(run.group("issue"))

    page = PAGE_RE.search(first) or PAGE_RE.search(collapsed_all)
    if page:
        result["page_start"] = int(page.group("page"))

    cite = CITATION_RE.search(collapsed_first) or CITATION_RE.search(collapsed_all)
    if cite:
        result["citation_raw"] = collapse(cite.group(0))
        result["authors"] = split_authors(cite.group("authors"))
        result["title"] = collapse(cite.group("title"))
        result["volume"] = int(cite.group("volume"))
        result["issue"] = int(cite.group("issue"))
        result["page_start"] = int(cite.group("start"))
        result["page_end"] = int(cite.group("end"))
        monthyear = cite.group("monthyear").strip()
        parts = monthyear.split()
        if parts:
            result["month"] = parts[0]
        if len(parts) > 1 and parts[-1].isdigit():
            result["year"] = int(parts[-1])

    if not result["title"]:
        # Lines after running header until author superscripts.
        lines = [ln.strip() for ln in first.splitlines() if ln.strip()]
        title_lines: list[str] = []
        seen_header = False
        for ln in lines:
            if RUNNING_HEADER_RE.search(ln) or ln.lower().startswith("international journal"):
                seen_header = True
                continue
            if not seen_header:
                continue
            if re.match(r"^(Citation\||Received\||Keywords:)", ln, re.IGNORECASE):
                break
            if re.search(r"\d+\s*,", ln) and re.search(r"[A-Z][a-z]+\s+[A-Z]", ln):
                break
            if EMAIL_RE.search(ln) or ln.lower().startswith("correspondence"):
                break
            title_lines.append(ln)
            if len(collapse(" ".join(title_lines))) > 220:
                break
        if title_lines:
            result["title"] = collapse(" ".join(title_lines[:4]))

    email = EMAIL_RE.search(first) or EMAIL_RE.search(collapsed_all)
    if email:
        result["correspondence_email"] = email.group(0)

    doi = DOI_RE.search(raw)
    if doi:
        result["doi"] = doi.group(0).rstrip(".")

    for match in DATE_FIELD_RE.finditer(collapsed_all):
        key = match.group(1).lower() + "_date"
        result[key] = collapse(match.group(2))

    result["keywords"] = extract_keywords(raw)
    result["abstract"] = extract_abstract(raw)

    # Affiliations: lines starting with a digit after authors.
    affs: list[str] = []
    for ln in first.splitlines():
        m = re.match(r"^(\d+)\s*(Department|Western|University|.+)$", ln.strip())
        if m and len(ln.strip()) > 8:
            affs.append(ln.strip())
    result["affiliations"] = affs[:12]
    return result


def strip_running_headers(text: str) -> str:
    lines = []
    for ln in text.splitlines():
        if RUNNING_HEADER_RE.search(ln) or PAGE_RE.search(ln):
            if len(ln.strip()) < 80:
                continue
        if ln.strip().lower().startswith("international journal of innovations"):
            continue
        lines.append(ln)
    return "\n".join(lines)


def split_paragraphs(text: str, *, min_len: int = 80) -> list[str]:
    cleaned = strip_running_headers(text)
    chunks: list[str] = []
    for block in re.split(r"\n\s*\n", cleaned):
        para = collapse(block)
        if len(para) < min_len:
            continue
        if para.lower().startswith("figure ") or para.lower().startswith("table "):
            continue
        chunks.append(para)
    if not chunks and collapse(cleaned):
        # Fallback: sliding windows of ~400 chars
        body = collapse(cleaned)
        for i in range(0, len(body), 400):
            piece = body[i : i + 500]
            if len(piece) >= min_len:
                chunks.append(piece)
    return chunks[:200]


def format_house_citation(
    *,
    authors: list[str] | None,
    title: str,
    volume: int,
    issue: int,
    page_start: int,
    page_end: Optional[int],
    month: Optional[str],
    year: Optional[int],
    abbreviation: str = "IJIST",
) -> str:
    author_part = ", ".join(authors or []) or "Authors"
    pages = f"{page_start}-{page_end}" if page_end else str(page_start)
    date = " ".join(p for p in (month, str(year) if year else None) if p)
    return (
        f"{author_part}, “{title}”, {abbreviation}, Vol. {volume} Issue. {issue} "
        f"pp {pages}" + (f", {date}" if date else "")
    )


parse_ijist_header = parse_ijist_header
format_house_citation = format_house_citation
