"""Fill published author-database rows from a journal OJS archive URL."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database.session import AsyncSessionLocal
from app.models.citation import AuthorArticle, AuthorCrawlJob
from app.schemas.author_db import AUTHOR_DB_JOURNALS, COMMENT_MAX, DEFAULT_STAGE_DAYS
from app.services.citation_parser import EMAIL_RE, MONTH_RE, format_emails, parse_ijist_header, split_authors
from app.services.pdf_text import extract_pdf_text
from app.services import crawler as crawler_mod

PAPER_ID_RE = re.compile(r"\b([A-Z]{2,10}[-–]\d{4}[-–]\d{1,5})\b")
ORCID_RE = re.compile(r"\b(?:https?://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\b", re.I)
MONTH_NUM = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


def _month_num(word: str) -> Optional[int]:
    key = re.sub(r"[^a-z]", "", (word or "").lower())
    if key in MONTH_NUM:
        return MONTH_NUM[key]
    if len(key) >= 3:
        for name, number in MONTH_NUM.items():
            if name.startswith(key):
                return number
    return None


def to_iso_date(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value).strip().strip("."))
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    match = re.fullmatch(r"(\d{4})[./](\d{1,2})[./](\d{1,2})", text)
    if match:
        year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    match = re.fullmatch(rf"({MONTH_RE})\.?\s+(\d{{1,2}}),?\s+(\d{{4}})", text, re.I)
    if match:
        month = _month_num(match.group(1))
        day = int(match.group(2))
        year = int(match.group(3))
        if month and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    match = re.fullmatch(rf"(\d{{1,2}})\s+({MONTH_RE})\.?\s+(\d{{4}})", text, re.I)
    if match:
        day = int(match.group(1))
        month = _month_num(match.group(2))
        year = int(match.group(3))
        if month and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return text[:32]


def _unique_join(values: list[str], sep: str = "; ") -> str:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        text = re.sub(r"\s+", " ", str(raw or "")).strip(" ;,")
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return sep.join(out)


def _journal_aliases(title: str, abbreviation: str) -> set[str]:
    aliases = {title.strip().lower(), abbreviation.strip().lower()}
    for abbr, name in AUTHOR_DB_JOURNALS:
        if title.strip().lower() in {abbr.lower(), name.lower()} or abbreviation.strip().lower() in {
            abbr.lower(),
            name.lower(),
        }:
            aliases.add(abbr.lower())
            aliases.add(name.lower())
    aliases.discard("")
    return aliases


def parse_ojs_article_html(html: str, page_url: str = "") -> dict[str, Any]:
    authors: list[str] = []
    emails: list[str] = []
    orcids: list[str] = []
    metas: dict[str, str] = {}
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup.find_all("meta"):
            name = (tag.get("name") or tag.get("property") or "").strip().lower()
            content = (tag.get("content") or "").strip()
            if not name or not content:
                continue
            if name in {"citation_author", "dc.creator"}:
                authors.append(content)
            elif name in {"citation_author_email"}:
                emails.append(content)
            elif name in {"citation_author_orcid"}:
                found = ORCID_RE.search(content)
                orcids.append(found.group(1) if found else content)
            else:
                metas[name] = content
        for tag in soup.find_all("a", href=True):
            href = str(tag.get("href") or "")
            if href.lower().startswith("mailto:"):
                emails.append(href.split(":", 1)[1].split("?", 1)[0])
            found = ORCID_RE.search(href)
            if found:
                orcids.append(found.group(1))
        title = (
            metas.get("citation_title")
            or metas.get("dc.title")
            or metas.get("og:title")
            or ""
        ).strip()
        if not title:
            heading = soup.find("h1")
            if heading:
                title = heading.get_text(" ", strip=True)
        blob = soup.get_text(" ", strip=True)
    except Exception:
        title = ""
        blob = html or ""
        for match in re.finditer(
            r'<meta\b[^>]*\bname=["\']([^"\']+)["\'][^>]*\bcontent=["\']([^"\']+)["\']',
            html or "",
            re.I,
        ):
            name = match.group(1).strip().lower()
            content = match.group(2).strip()
            if name in {"citation_author", "dc.creator"}:
                authors.append(content)
            elif name == "citation_title":
                title = title or content
            elif name in {"citation_doi", "dc.identifier"}:
                metas[name] = content
            elif name in {"citation_publication_date", "citation_date", "citation_online_date"}:
                metas[name] = content
        for match in EMAIL_RE.finditer(html or ""):
            emails.append(match.group(0))

    doi = (metas.get("citation_doi") or metas.get("dc.identifier") or "").strip()
    if doi.lower().startswith("doi:"):
        doi = doi[4:].strip()
    if "doi.org/" in doi.lower():
        doi = doi.split("doi.org/", 1)[1].strip()
    paper = PAPER_ID_RE.search(blob) or PAPER_ID_RE.search(html or "") or PAPER_ID_RE.search(page_url)
    published = (
        metas.get("citation_publication_date")
        or metas.get("citation_online_date")
        or metas.get("citation_date")
        or metas.get("dc.date")
        or ""
    )
    received = metas.get("citation_received_date") or metas.get("dc.date.created") or ""
    accepted = metas.get("citation_accepted_date") or ""
    for match in EMAIL_RE.finditer(blob):
        emails.append(match.group(0))
    for match in ORCID_RE.finditer(blob):
        orcids.append(match.group(1))
    return {
        "title": title,
        "authors": authors,
        "emails": emails,
        "orcids": orcids,
        "doi": doi,
        "paper_id": paper.group(1).replace("–", "-") if paper else "",
        "received_date": received,
        "accepted_date": accepted,
        "publish_date": published,
        "pdf_url": metas.get("citation_pdf_url") or "",
    }


def _authors_text(values: list[str] | None) -> str:
    names: list[str] = []
    for item in values or []:
        names.extend(split_authors(item) if "," in item else [item])
    return _unique_join(names)


def _snapshot(row: AuthorArticle) -> dict[str, Any]:
    return {
        "journal_id": row.journal_id,
        "journal_title": row.journal_title or "",
        "ojs_number": row.ojs_number or "",
        "title": row.title or "",
        "author_names": row.author_names or "",
        "author_emails": row.author_emails or "",
        "orcid_id": row.orcid_id or "",
        "received_date": row.received_date,
        "accepted_date": row.accepted_date,
        "publish_date": row.publish_date,
        "editorial_status": row.editorial_status or "Published",
        "comments": row.comments or "",
        "doi_in_pdf": row.doi_in_pdf or "",
    }


def _same_journal(row: AuthorArticle, title: str, abbreviation: str) -> bool:
    wanted = _journal_aliases(title, abbreviation)
    have = _journal_aliases(row.journal_title or "", "")
    return bool(wanted & have) if wanted and have else True


async def _existing_published(
    db: AsyncSession,
    ojs_number: str,
    title: str,
    journal_title: str,
    abbreviation: str,
) -> Optional[AuthorArticle]:
    if ojs_number:
        rows = list(
            (
                await db.execute(
                    select(AuthorArticle).where(
                        AuthorArticle.wing == "published",
                        AuthorArticle.ojs_number == ojs_number,
                    )
                )
            ).scalars().all()
        )
        for row in rows:
            if _same_journal(row, journal_title, abbreviation):
                return row
        if rows:
            return rows[0]
    if title:
        rows = list(
            (
                await db.execute(
                    select(AuthorArticle).where(
                        AuthorArticle.wing == "published",
                        AuthorArticle.title == title,
                    )
                )
            ).scalars().all()
        )
        for row in rows:
            if _same_journal(row, journal_title, abbreviation):
                return row
    return None


def _int_or_none(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _page_text(pdf_meta: dict[str, Any]) -> str:
    start = pdf_meta.get("page_start")
    end = pdf_meta.get("page_end")
    if start and end:
        return f"{start}-{end}"
    if start:
        return str(start)
    return ""


def _collect_targets(inventory: list[dict]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for issue in inventory:
        landings = [str(url) for url in (issue.get("article_urls") or []) if url]
        pdfs = [str(url) for url in (issue.get("pdf_urls") or []) if url]
        pdf_by_id: dict[str, str] = {}
        for pdf in pdfs:
            aid = crawler_mod._article_id(pdf)
            if aid and aid not in pdf_by_id:
                pdf_by_id[aid] = pdf
        volume = issue.get("volume")
        number = issue.get("issue_number")
        for landing in landings:
            aid = crawler_mod._article_id(landing) or landing
            if aid in seen:
                continue
            seen.add(aid)
            targets.append(
                {
                    "landing": landing,
                    "pdf": pdf_by_id.get(crawler_mod._article_id(landing) or "", ""),
                    "article_id": crawler_mod._article_id(landing) or "",
                    "volume": volume,
                    "issue": number,
                }
            )
        for aid, pdf in pdf_by_id.items():
            if aid in seen:
                continue
            seen.add(aid)
            targets.append(
                {
                    "landing": pdf,
                    "pdf": pdf,
                    "article_id": aid,
                    "volume": volume,
                    "issue": number,
                }
            )
    return targets


def _ojs_number(html_meta: dict[str, Any], pdf_meta: dict[str, Any], abbreviation: str, article_id: str) -> str:
    paper = str(html_meta.get("paper_id") or "").strip()
    if paper:
        return paper
    blob = " ".join(
        str(pdf_meta.get(key) or "")
        for key in ("header_raw", "citation_raw", "title", "doi")
    )
    match = PAPER_ID_RE.search(blob)
    if match:
        return match.group(1).replace("–", "-")
    doi = str(html_meta.get("doi") or pdf_meta.get("doi") or "")
    if abbreviation and doi.upper().startswith(f"10.") and abbreviation.upper() in doi.upper():
        tail = doi.rsplit("/", 1)[-1]
        digits = re.findall(r"\d+", tail)
        if digits:
            return f"{abbreviation}-{digits[-1]}"
    if abbreviation and article_id:
        return f"{abbreviation}-{article_id}"
    return article_id or doi or ""


async def _extract_article(
    fetch,
    target: dict[str, Any],
    abbreviation: str,
    journal_title: str,
    delay: float,
) -> dict[str, Any]:
    landing = target.get("landing") or ""
    pdf_url = target.get("pdf") or ""
    article_id = target.get("article_id") or crawler_mod._article_id(landing) or ""
    html_meta: dict[str, Any] = {}
    pdf_meta: dict[str, Any] = {}
    comments = f"Article URL: {landing}" if landing else ""

    if landing:
        try:
            status, body, ctype = await fetch(landing)
        except Exception as exc:
            raise RuntimeError(f"{landing}: {exc}") from exc
        if status >= 400:
            raise RuntimeError(f"{landing}: HTTP {status}")
        if crawler_mod._is_pdf_payload(body, ctype):
            pdf_url = pdf_url or landing
        elif crawler_mod._is_html_payload(body, ctype):
            html = body.decode("utf-8", errors="ignore")
            html_meta = parse_ojs_article_html(html, landing)
            if not pdf_url:
                pdf_url = str(html_meta.get("pdf_url") or "")
            if not pdf_url and article_id:
                found = await crawler_mod._pdfs_from_article_page(fetch, landing, article_id, delay)
                if found:
                    pdf_url = found[0]

    if pdf_url:
        try:
            status, body, ctype = await fetch(pdf_url)
        except Exception as exc:
            if not html_meta:
                raise RuntimeError(f"{pdf_url}: {exc}") from exc
        else:
            if status < 400 and crawler_mod._is_pdf_payload(body, ctype):
                text, _status = extract_pdf_text(body)
                if text:
                    pdf_meta = parse_ijist_header(
                        text, journal_name=journal_title, abbreviation=abbreviation or None
                    )

    title = (pdf_meta.get("title") or html_meta.get("title") or "").strip()
    authors = _authors_text(pdf_meta.get("authors") or html_meta.get("authors") or [])
    emails = format_emails(
        _unique_join(
            [pdf_meta.get("correspondence_email") or ""] + list(html_meta.get("emails") or [])
        )
    )
    orcids = _unique_join(list(html_meta.get("orcids") or []))
    doi = (pdf_meta.get("doi") or html_meta.get("doi") or "").strip()
    ojs = _ojs_number(html_meta, pdf_meta, abbreviation, article_id)
    received = to_iso_date(pdf_meta.get("received_date") or html_meta.get("received_date"))
    accepted = to_iso_date(pdf_meta.get("accepted_date") or html_meta.get("accepted_date"))
    published = to_iso_date(pdf_meta.get("published_date") or html_meta.get("publish_date"))
    if comments and len(comments) > COMMENT_MAX:
        comments = comments[:COMMENT_MAX]
    return {
        "ojs_number": ojs,
        "title": title,
        "author_names": authors,
        "author_emails": emails,
        "orcid_id": orcids,
        "received_date": received,
        "accepted_date": accepted,
        "publish_date": published,
        "doi_in_pdf": doi,
        "comments": comments,
        "volume": _int_or_none(pdf_meta.get("volume") if pdf_meta.get("volume") else target.get("volume")),
        "issue": _int_or_none(pdf_meta.get("issue") if pdf_meta.get("issue") else target.get("issue")),
        "page": _page_text(pdf_meta),
    }


async def run_author_crawl_job(job_id: int, fetch=None, delay: float = 0.0) -> None:
    if fetch is None:
        fetch = crawler_mod.default_fetch
    async with AsyncSessionLocal() as db:
        job = await db.get(AuthorCrawlJob, job_id)
        if job is None:
            return
        job.status = "running"
        job.phase = "scanning"
        job.message = "Listing issues and articles from the archive…"
        job.started_at = datetime.now(timezone.utc)
        job.error_log = list(job.error_log or [])
        job.inventory = []
        job.articles_saved = 0
        job.articles_skipped = 0
        job.articles_already = 0
        job.articles_failed = 0
        await db.commit()
        try:
            await crawler_mod._scan_issues(db, job, fetch, delay)
            if job.cancel_requested:
                job.status = "cancelled"
                job.phase = "cancelled"
                job.message = "Archive crawl cancelled."
                job.finished_at = datetime.now(timezone.utc)
                await db.commit()
                return
            targets = _collect_targets(list(job.inventory or []))
            job.articles_found = len(targets)
            job.phase = "importing"
            job.message = f"Found {len(targets)} articles. Saving published records…"
            flag_modified(job, "inventory")
            await crawler_mod._commit_progress(db, job)
            abbreviation = (job.journal_abbreviation or "").strip()
            journal_title = (job.journal_title or "").strip()
            for index, target in enumerate(targets):
                job = await db.get(AuthorCrawlJob, job_id)
                if job is None:
                    return
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.phase = "cancelled"
                    job.message = "Archive crawl cancelled."
                    job.finished_at = datetime.now(timezone.utc)
                    await db.commit()
                    return
                left = max(0, len(targets) - index)
                job.message = (
                    f"Saving published articles… {job.articles_saved} added, "
                    f"{job.articles_already} already stored, {left} left."
                )
                if index == 0 or index % 2 == 0:
                    await crawler_mod._commit_progress(db, job)
                try:
                    payload = await _extract_article(
                        fetch, target, abbreviation, journal_title, delay
                    )
                except Exception as exc:
                    job.articles_failed += 1
                    job.articles_skipped += 1
                    job.error_log = (job.error_log or []) + [str(exc)]
                    flag_modified(job, "error_log")
                    continue
                if not payload.get("title") and not payload.get("ojs_number"):
                    job.articles_failed += 1
                    job.articles_skipped += 1
                    continue
                existing = await _existing_published(
                    db,
                    payload.get("ojs_number") or "",
                    payload.get("title") or "",
                    journal_title,
                    abbreviation,
                )
                if existing is not None:
                    job.articles_already += 1
                    job.articles_skipped += 1
                    continue
                row = AuthorArticle(
                    wing="published",
                    journal_id=None,
                    journal_title=journal_title,
                    owner_id=job.owner_id,
                    ojs_number=payload.get("ojs_number") or "",
                    title=payload.get("title") or "",
                    author_names=payload.get("author_names") or "",
                    author_emails=payload.get("author_emails") or "",
                    plagiarism="",
                    orcid_id=payload.get("orcid_id") or "",
                    received_date=payload.get("received_date"),
                    accepted_date=payload.get("accepted_date"),
                    publish_date=payload.get("publish_date"),
                    editorial_status="Published",
                    comments=payload.get("comments") or "",
                    current_stage="",
                    current_stage_days=DEFAULT_STAGE_DAYS,
                    doi_in_pdf=payload.get("doi_in_pdf") or "",
                    volume=_int_or_none(payload.get("volume")),
                    issue_number=_int_or_none(payload.get("issue")),
                    page=payload.get("page") or "",
                    review_rounds=[],
                )
                db.add(row)
                await db.flush()
                row.original_snapshot = _snapshot(row)
                flag_modified(row, "original_snapshot")
                job.articles_saved += 1
            job = await db.get(AuthorCrawlJob, job_id)
            if job is None:
                return
            job.status = "completed"
            job.phase = "completed"
            job.message = (
                f"Crawl finished. Added {job.articles_saved} published articles, "
                f"{job.articles_already} already stored"
                + (f", {job.articles_failed} failed" if job.articles_failed else "")
                + ". Export the spreadsheet to fill author emails, then import again."
            )
            job.finished_at = datetime.now(timezone.utc)
        except Exception as exc:
            job.status = "failed"
            job.phase = "failed"
            job.message = f"Archive crawl failed: {exc}"
            job.error_log = (job.error_log or []) + [str(exc)]
            job.finished_at = datetime.now(timezone.utc)
        await db.commit()
