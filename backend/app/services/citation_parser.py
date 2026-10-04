"""Parse 50sea galley first-page headers (IJIST, FCSI, and the same Citation| layout)."""

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
QOPEN = r"[“\"\"]"
QCLOSE = r"[”\"\"]"

RUNNING_HEADER_RE = re.compile(
    rf"(?P<month>{MONTH_RE})\s+(?P<year>\d{{4}})\s*\|\s*Vol\.?\s*(?P<volume>\d+)\s*\|\s*Issue\.?\s*(?P<issue>\d+)",
    re.IGNORECASE,
)
PAGE_RE = re.compile(r"Page\s*\|\s*(?P<page>\d+)", re.IGNORECASE)
CITATION_RE = re.compile(
    rf"Citation\s*\|\s*(?P<authors>.+?),\s*{QOPEN}(?P<title>.+?){QCLOSE}\s*,\s*"
    rf"(?P<venue>[A-Za-z][A-Za-z0-9 .&/-]{{1,80}}?)\s*,\s*"
    rf"Vol\.\s*(?P<volume>\d+)\s*Issue\.?\s*(?P<issue>\d+)\s*"
    rf"pp\s*(?P<start>\d+)\s*(?:-\s*(?P<end>\d+))?\s*,\s*(?P<monthyear>{MONTH_RE}\.?\s+\d{{4}})",
    re.IGNORECASE | re.DOTALL,
)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
DOI_LINE_RE = re.compile(
    r"DOI\s*\|\s*(?:https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[-._;()/:A-Z0-9]+)",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
_EMAIL_TLD2 = r"co\.uk|ac\.uk|edu\.pk|gov\.pk|org\.pk|com\.pk|net\.pk|ac\.in|co\.in|edu\.au|com\.au"
_EMAIL_TLD1 = r"com|org|net|edu|gov|mil|int|info|biz|io|pk|uk|au|us|de|fr|ca|za|np|bd|sa|ae"
GLUED_EMAIL_RE = re.compile(
    rf"(\.(?:{_EMAIL_TLD2})|\.(?:{_EMAIL_TLD1}))(?=[A-Z0-9._%+\-]+@)",
    re.IGNORECASE,
)


def extract_emails(text: str) -> list[str]:
    """Split glued addresses such as a@x.compb@y.com into separate emails."""
    blob = GLUED_EMAIL_RE.sub(r"\1 ", str(text or ""))
    blob = re.sub(r"[;,]+", " ", blob)
    seen: set[str] = set()
    out: list[str] = []
    for match in EMAIL_RE.finditer(blob):
        email = match.group(0).strip().rstrip(".,);")
        key = email.lower()
        if key and key not in seen:
            seen.add(key)
            out.append(email)
    return out


def format_emails(text: str, *, excel: bool = False) -> str:
    emails = extract_emails(text)
    if emails:
        sep = ";\n" if excel else "; "
        return sep.join(emails)
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip(" ;,")
    return cleaned
DATE_FIELD_RE = re.compile(
    rf"(Received|Revised|Accepted|Published)\s*\|\s*({MONTH_RE}\.?\s+\d{{1,2}},?\s+\d{{4}}|{MONTH_RE}\.?\s+\d{{1,2}}\s+\d{{4}})",
    re.IGNORECASE,
)
JOURNAL_BANNER_RE = re.compile(
    r"^(international journal of|frontiers in computational|frontiers in )\b",
    re.I,
)
AUTHOR_LINE_RE = re.compile(
    r"^[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,5}\d*"
    r"(?:\s*,\s*[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,5}\d*)+$"
)
DROP_CAP_RE = re.compile(r"^[A-Z]$")
REFERENCES_HEADING_RE = re.compile(
    r"^(references|bibliography|works cited|literature cited)\s*$",
    re.I,
)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n"))


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_authors(raw: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", raw).strip().rstrip(",")
    cleaned = re.sub(r"\d+", "", cleaned)
    parts = re.split(r"\s*,\s*", cleaned)
    return [p.strip(" .") for p in parts if p.strip(" .")]


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
    start = None
    pub = re.search(r"Published\s*\|[^\n]+\n", collapsed_lines, re.IGNORECASE)
    if pub:
        start = pub.end()
    else:
        rec = re.search(r"Received\s*\|", collapsed_lines, re.IGNORECASE)
        if rec:
            nl = collapsed_lines.find("\n", rec.start())
            start = nl + 1 if nl != -1 else rec.end()
    if start is None:
        return None
    rest = collapsed_lines[start:]
    kw = re.search(r"\nKeywords\s*:", rest, re.IGNORECASE)
    body = rest[: kw.start()] if kw else rest[:2500]
    body = re.sub(r"^\s*T\s*\n", "", body)
    body = collapse(body)
    return body[:4000] if body else None


def _is_journal_banner(line: str, journal_name: str | None = None, abbreviation: str | None = None) -> bool:
    compact = collapse(line)
    if not compact or DROP_CAP_RE.match(compact):
        return True
    low = compact.lower()
    if JOURNAL_BANNER_RE.match(compact):
        return True
    if abbreviation and low == abbreviation.lower():
        return True
    if journal_name:
        name = collapse(journal_name).lower()
        if name and (low == name or low.startswith(name[:24])):
            return True
    return False


def _looks_like_title(text: str) -> bool:
    compact = collapse(text)
    if len(compact) < 8 or len(compact) > 220:
        return False
    if compact[:1].islower():
        return False
    if compact.lower().startswith(("this ", "the increasing", "introduction", "keywords")):
        return False
    sentences = compact.count(". ")
    return sentences <= 1


def parse_ijist_header(
    text: str,
    *,
    journal_name: str | None = None,
    abbreviation: str | None = None,
) -> dict[str, Any]:
    """Extract bibliographic fields from a 50sea galley (IJIST, FCSI, same layout)."""
    raw = text or ""
    first = "\n".join(raw.splitlines()[:90])
    collapsed_first = collapse(first)
    collapsed_all = collapse(raw[:12000])

    result: dict[str, Any] = {
        "journal_name": journal_name or "International Journal of Innovations in Science & Technology",
        "abbreviation": abbreviation or "IJIST",
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
        venue = collapse(cite.group("venue"))
        if venue.isupper() or (len(venue) <= 12 and " " not in venue):
            result["abbreviation"] = venue.upper()
        else:
            result["journal_name"] = venue
        result["volume"] = int(cite.group("volume"))
        result["issue"] = int(cite.group("issue"))
        result["page_start"] = int(cite.group("start"))
        if cite.group("end"):
            result["page_end"] = int(cite.group("end"))
        monthyear = cite.group("monthyear").strip()
        parts = monthyear.split()
        if parts:
            result["month"] = parts[0]
        if len(parts) > 1 and parts[-1].isdigit():
            result["year"] = int(parts[-1])

    if not result["title"]:
        lines = [ln.strip() for ln in first.splitlines() if ln.strip()]
        title_lines: list[str] = []
        seen_header = False
        for ln in lines:
            if RUNNING_HEADER_RE.search(ln) or PAGE_RE.search(ln) or _is_journal_banner(
                ln, journal_name, abbreviation
            ):
                seen_header = True
                continue
            if not seen_header:
                if JOURNAL_BANNER_RE.match(ln) or (journal_name and ln.lower().startswith(journal_name.lower()[:12])):
                    seen_header = True
                continue
            if re.match(r"^(Citation\s*\| |Received\s*\| |Keywords\s*:)", ln, re.IGNORECASE):
                break
            if EMAIL_RE.search(ln) or ln.lower().startswith("correspondence"):
                break
            if AUTHOR_LINE_RE.match(ln) or (re.search(r"\d+\s*,", ln) and re.search(r"[A-Z][a-z]+\s+[A-Z]", ln)):
                if not result["authors"]:
                    result["authors"] = split_authors(re.sub(r"\d+", "", ln))
                break
            if DROP_CAP_RE.match(ln):
                continue
            title_lines.append(ln)
            if len(collapse(" ".join(title_lines))) > 180:
                break
        guessed = collapse(" ".join(title_lines[:6])) if title_lines else ""
        if guessed and _looks_like_title(guessed):
            result["title"] = guessed
        elif guessed and not result["title"]:
            result["title"] = guessed[:180]

    email = EMAIL_RE.search(first) or EMAIL_RE.search(collapsed_all)
    if email:
        result["correspondence_email"] = email.group(0)

    doi_line = DOI_LINE_RE.search(raw) or DOI_LINE_RE.search(collapsed_all)
    if doi_line:
        result["doi"] = doi_line.group(1).rstrip(".")
    else:
        doi = DOI_RE.search(raw)
        if doi:
            result["doi"] = doi.group(0).rstrip(".")

    for match in DATE_FIELD_RE.finditer(collapsed_all):
        key = match.group(1).lower() + "_date"
        result[key] = collapse(match.group(2))

    result["keywords"] = extract_keywords(raw)
    result["abstract"] = extract_abstract(raw)

    affs: list[str] = []
    for ln in first.splitlines():
        m = re.match(r"^(\d+)\s*(Department|Western|University|Faculty|School|College|Institute|.+)$", ln.strip())
        if m and len(ln.strip()) > 8:
            affs.append(ln.strip())
    result["affiliations"] = affs[:12]
    return result


def strip_running_headers(text: str) -> str:
    lines = []
    for ln in text.splitlines():
        if RUNNING_HEADER_RE.search(ln) or PAGE_RE.search(ln):
            if len(ln.strip()) < 90:
                continue
        if JOURNAL_BANNER_RE.match(ln.strip()) or ln.strip().lower().startswith("international journal of"):
            continue
        if DROP_CAP_RE.match(ln.strip()):
            continue
        lines.append(ln)
    return "\n".join(lines)


def split_paragraphs(text: str, *, min_len: int = 80) -> list[str]:
    cleaned = strip_running_headers(text)
    cut = re.split(
        r"\n\s*(?:References|Bibliography|Works Cited|Literature Cited)\s*\n",
        cleaned,
        maxsplit=1,
        flags=re.I,
    )
    cleaned = cut[0]
    chunks: list[str] = []
    for block in re.split(r"\n\s*\n", cleaned):
        para = collapse(block)
        if len(para) < min_len:
            continue
        if para.lower().startswith("figure ") or para.lower().startswith("table "):
            continue
        if REFERENCES_HEADING_RE.match(para):
            break
        chunks.append(para)
    if not chunks and collapse(cleaned):
        body = collapse(cleaned)
        for i in range(0, len(body), 400):
            piece = body[i : i + 500]
            if len(piece) >= min_len:
                chunks.append(piece)
    return chunks[:200]


def _ieee_authors(authors: list[str] | None) -> str:
    names = [name.strip() for name in (authors or []) if str(name).strip()]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


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
    journal_name: Optional[str] = None,
    doi: Optional[str] = None,
) -> str:
    """IEEE-style numbered reference used in the Word review file."""
    author_part = _ieee_authors(authors)
    venue = (journal_name or "").strip() or abbreviation
    if journal_name and abbreviation and abbreviation.upper() not in journal_name.upper():
        venue = f"{journal_name} ({abbreviation})"
    pages = f"{page_start}-{page_end}" if page_end else str(page_start)
    date = " ".join(p for p in (month, str(year) if year else None) if p)
    title_clean = collapse(title or "").strip(" .")
    parts = []
    if author_part:
        parts.append(f"{author_part},")
    if title_clean:
        parts.append(f"“{title_clean},”")
    loc = f"{venue}, vol. {volume}, no. {issue}, pp. {pages}"
    if date:
        loc += f", {date}"
    if doi:
        doi_value = doi.replace("https://doi.org/", "").replace("http://dx.doi.org/", "").strip()
        loc += f", doi: {doi_value}"
    parts.append(loc)
    return " ".join(parts) + "."


def metadata_looks_broken(
    title: str | None,
    authors: list | None,
    *,
    journal_name: str | None = None,
) -> bool:
    names = [a for a in (authors or []) if str(a).strip()]
    compact = collapse(title or "")
    if not names:
        return True
    if not compact or compact.lower() in {"untitled article", "authors"}:
        return True
    if compact[:1].islower():
        return True
    if journal_name and compact.lower().startswith(collapse(journal_name).lower()[:24]):
        return True
    if JOURNAL_BANNER_RE.match(compact):
        return True
    if len(compact) > 220 and compact.count(". ") >= 1:
        return True
    return False


parse_ijist_header = parse_ijist_header
format_house_citation = format_house_citation
metadata_looks_broken = metadata_looks_broken
