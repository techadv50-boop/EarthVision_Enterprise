"""Fast OJS archive inventory, then download PDFs only for issues the operator selects."""

from __future__ import annotations

import asyncio
import re
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database.session import AsyncSessionLocal
from app.models.citation import CrawlJob, Journal
from app.services.ingest import ingest_pdf_bytes

USER_AGENT = "CitationAssistant/1.0 (journal archive ingest)"
MAX_ARCHIVE_PAGES = 80
ISSUE_CONCURRENCY = 12

ISSUE_VIEW_HREF = re.compile(r"/issue/view/\d+", re.I)
ARCHIVE_HREF = re.compile(r"/issue/archive(?:/\d+)?/?$", re.I)
ARTICLE_VIEW_HREF = re.compile(r"/article/view/(\d+)(?:/(\d+))?", re.I)
ARTICLE_DOWNLOAD_HREF = re.compile(r"/article/download/", re.I)
VOL_ISSUE_HREF = re.compile(
    r"Vol\.?\s*(\d+)\s*(?:No\.?|Issue)\s*(\d+)(?:\s*\((\d{4})\))?",
    re.I,
)

SKIP_PATH = re.compile(
    r"(login|logout|register|lostPassword|search|\$\$\$call\$\$\$|"
    r"/user/|/notification|/comment|/gateway/|/api/|"
    r"/about|/contact|/privacy|/information/|"
    r"/submission|/editorialTeam|/reviewer)",
    re.I,
)
SKIP_EXT = re.compile(
    r"\.(?:css|js|mjs|map|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|eot|mp4|zip|xml|rss)(?:$|\?)",
    re.I,
)
PDF_LINK_TEXT = re.compile(
    r"^\s*(pdf|download\s*pdf|full[- ]text(?:\s*pdf)?|view\s*pdf)\s*$",
    re.I,
)


def _same_host(root: str, url: str) -> bool:
    return (urlparse(root).hostname or "").lower() == (urlparse(url).hostname or "").lower()


def _clean(url: str) -> str:
    return urldefrag(url)[0].strip()


def is_pdf_url(url: str, link_text: str = "") -> bool:
    path = (urlparse(url).path or "").lower()
    if path.endswith(".pdf") or ".pdf?" in url.lower():
        return True
    if ARTICLE_DOWNLOAD_HREF.search(path) or "/download/" in path:
        return True
    match = ARTICLE_VIEW_HREF.search(path)
    if match and match.group(2):
        return True
    if "galley" in path and "pdf" in (path + " " + (link_text or "").lower()):
        return True
    if PDF_LINK_TEXT.match(link_text or ""):
        return True
    return False


def extract_anchors(html: str, base: str) -> list[tuple[str, str]]:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        out: list[tuple[str, str]] = []
        for tag in soup.find_all("a", href=True):
            href = _clean(urljoin(base, tag["href"]))
            text = tag.get_text(" ", strip=True)
            out.append((href, text))
        return out
    except ImportError:
        pairs: list[tuple[str, str]] = []
        for match in re.finditer(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S
        ):
            href = _clean(urljoin(base, match.group(1)))
            text = re.sub(r"<[^>]+>", " ", match.group(2))
            pairs.append((href, re.sub(r"\s+", " ", text).strip()))
        return pairs


def extract_links(html: str, base: str) -> list[str]:
    return [url for url, _text in extract_anchors(html, base)]


async def default_fetch(url: str) -> tuple[int, bytes, str]:
    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:
        resp = await client.get(url)
        return resp.status_code, resp.content, resp.headers.get("content-type") or ""


def _is_pdf_payload(content: bytes, content_type: str) -> bool:
    return content[:5] == b"%PDF-" or "pdf" in (content_type or "").lower()


def _is_html_payload(content: bytes, content_type: str) -> bool:
    ctype = (content_type or "").lower()
    if "html" in ctype or "xml" in ctype:
        return True
    head = content[:200].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _parse_vol_issue(text: str) -> tuple[int | None, int | None, int | None]:
    match = VOL_ISSUE_HREF.search(text or "")
    if not match:
        return None, None, None
    year = int(match.group(3)) if match.group(3) else None
    return int(match.group(1)), int(match.group(2)), year


def _unique(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


async def _commit_progress(db: AsyncSession, job: CrawlJob) -> None:
    await db.commit()
    await db.refresh(job)


def _inventory_message(job: CrawlJob) -> str:
    issues = int(job.issues_found or 0)
    articles = int(job.articles_found or 0)
    return f"Found {issues} issues · {articles} articles. Choose which issues to download."


async def run_crawl_job(job_id: int, fetch=default_fetch, delay: float = 0.0) -> None:
    """Scan the archive for issues and article counts. Does not download PDFs."""
    async with AsyncSessionLocal() as db:
        job = await db.get(CrawlJob, job_id)
        if job is None:
            return
        journal = await db.get(Journal, job.journal_id)
        if journal is None:
            job.status = "failed"
            job.error_log = (job.error_log or []) + ["Journal not found"]
            job.finished_at = datetime.now(timezone.utc)
            await db.commit()
            return
        job.status = "running"
        job.phase = "scanning"
        job.message = "Listing issues and article counts…"
        job.started_at = datetime.now(timezone.utc)
        job.error_log = list(job.error_log or [])
        job.inventory = []
        await db.commit()
        try:
            await _scan_issues(db, job, fetch, delay)
            if job.cancel_requested:
                job.status = "cancelled"
                job.phase = "cancelled"
                job.message = "Issue scan cancelled."
                job.finished_at = datetime.now(timezone.utc)
            else:
                job.status = "awaiting_selection"
                job.phase = "awaiting_selection"
                job.message = _inventory_message(job)
        except Exception as exc:
            job.status = "failed"
            job.phase = "failed"
            job.message = f"Issue scan failed: {exc}"
            job.error_log = (job.error_log or []) + [str(exc)]
            job.finished_at = datetime.now(timezone.utc)
        await db.commit()


async def run_download_job(
    job_id: int,
    issue_urls: list[str],
    fetch=default_fetch,
    delay: float = 0.02,
) -> None:
    """Download PDFs only for the issues the operator selected."""
    async with AsyncSessionLocal() as db:
        job = await db.get(CrawlJob, job_id)
        if job is None:
            return
        journal = await db.get(Journal, job.journal_id)
        if journal is None:
            job.status = "failed"
            job.message = "Journal not found"
            await db.commit()
            return
        inventory = list(job.inventory or [])
        selected = {_clean(url) for url in issue_urls}
        chosen = [row for row in inventory if _clean(str(row.get("url") or "")) in selected]
        pdf_urls: list[str] = []
        for row in chosen:
            pdf_urls.extend(row.get("pdf_urls") or [])
        pdf_urls = _unique(pdf_urls)
        job.status = "running"
        job.phase = "downloading"
        job.articles_found = len(pdf_urls)
        job.articles_saved = 0
        job.articles_skipped = 0
        job.cancel_requested = False
        job.finished_at = None
        job.message = (
            f"Downloading {len(pdf_urls)} PDFs from {len(chosen)} selected issue(s)…"
        )
        await db.commit()
        try:
            await _download_pdfs(db, job, journal, pdf_urls, fetch, delay)
            if job.cancel_requested:
                job.status = "cancelled"
                job.phase = "cancelled"
                job.message = (
                    f"Download cancelled. Loaded {job.articles_saved}, "
                    f"{max(0, job.articles_found - job.articles_saved - job.articles_skipped)} left."
                )
            else:
                job.status = "completed"
                job.phase = "completed"
                job.message = (
                    f"Done. Loaded {job.articles_saved} PDFs from {len(chosen)} issue(s), "
                    f"skipped {job.articles_skipped}."
                )
                for row in inventory:
                    if _clean(str(row.get("url") or "")) in selected:
                        row["downloaded"] = True
                job.inventory = inventory
                flag_modified(job, "inventory")
        except Exception as exc:
            job.status = "failed"
            job.phase = "failed"
            job.message = f"Download failed: {exc}"
            job.error_log = (job.error_log or []) + [str(exc)]
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()


async def _scan_issues(db: AsyncSession, job: CrawlJob, fetch, delay: float) -> None:
    archive = job.archive_url
    queue: deque[str] = deque([_clean(archive)])
    seen_pages: set[str] = set()
    issues: dict[str, dict] = {}

    while queue and len(seen_pages) < MAX_ARCHIVE_PAGES:
        if job.cancel_requested:
            return
        page_url = queue.popleft()
        if page_url in seen_pages:
            continue
        seen_pages.add(page_url)
        job.pages_crawled = len(seen_pages)
        job.message = f"Reading archive page {len(seen_pages)}…"
        await _commit_progress(db, job)
        if delay:
            await asyncio.sleep(delay)
        try:
            status, body, ctype = await fetch(page_url)
        except Exception as exc:
            job.error_log = (job.error_log or []) + [f"{page_url}: {exc}"]
            continue
        if status >= 400 or not _is_html_payload(body, ctype):
            continue
        html = body.decode("utf-8", errors="ignore")
        for href, text in extract_anchors(html, page_url):
            if not href or not _same_host(archive, href):
                continue
            path = urlparse(href).path or ""
            if SKIP_PATH.search(path) or SKIP_EXT.search(path):
                continue
            if ARCHIVE_HREF.search(href) and href not in seen_pages:
                queue.append(href)
            if ISSUE_VIEW_HREF.search(href):
                key = _clean(href)
                title = text or key
                volume, number, year = _parse_vol_issue(title)
                if key not in issues:
                    issues[key] = {
                        "url": key,
                        "title": title,
                        "volume": volume,
                        "issue_number": number,
                        "year": year,
                        "article_count": 0,
                        "pdf_urls": [],
                        "downloaded": False,
                    }
                elif title and len(title) > len(str(issues[key].get("title") or "")):
                    issues[key]["title"] = title
                    if volume:
                        issues[key]["volume"] = volume
                        issues[key]["issue_number"] = number
                        issues[key]["year"] = year

    issue_list = list(issues.values())
    job.issues_found = len(issue_list)
    job.message = f"Found {len(issue_list)} issues. Counting articles…"
    await _commit_progress(db, job)

    semaphore = asyncio.Semaphore(ISSUE_CONCURRENCY)

    async def inspect(row: dict) -> dict:
        async with semaphore:
            if delay:
                await asyncio.sleep(delay)
            try:
                status, body, ctype = await fetch(row["url"])
            except Exception as exc:
                row["error"] = str(exc)
                return row
            if status >= 400 or not _is_html_payload(body, ctype):
                return row
            html = body.decode("utf-8", errors="ignore")
            heading = _parse_vol_issue(html)
            if heading[0] and not row.get("volume"):
                row["volume"], row["issue_number"], row["year"] = heading
            article_ids: set[str] = set()
            pdfs: list[str] = []
            for href, text in extract_anchors(html, row["url"]):
                if not _same_host(archive, href):
                    continue
                match = ARTICLE_VIEW_HREF.search(href)
                if match:
                    article_ids.add(match.group(1))
                    if match.group(2) or is_pdf_url(href, text):
                        pdfs.append(_clean(href))
                elif is_pdf_url(href, text):
                    pdfs.append(_clean(href))
            row["pdf_urls"] = _unique(pdfs)
            row["article_count"] = len(article_ids) or len(row["pdf_urls"])
            return row

    inspected = await asyncio.gather(*(inspect(row) for row in issue_list))
    inspected.sort(
        key=lambda row: (
            -(row.get("volume") or 0),
            -(row.get("issue_number") or 0),
            str(row.get("title") or ""),
        )
    )
    job.inventory = inspected
    flag_modified(job, "inventory")
    job.issues_found = len(inspected)
    job.articles_found = sum(int(row.get("article_count") or 0) for row in inspected)
    job.pages_crawled = len(seen_pages) + len(inspected)
    job.message = _inventory_message(job)
    await _commit_progress(db, job)


async def _download_pdfs(
    db: AsyncSession,
    job: CrawlJob,
    journal: Journal,
    pdf_urls: list[str],
    fetch,
    delay: float,
) -> None:
    for index, pdf_url in enumerate(pdf_urls):
        if job.cancel_requested:
            return
        left = max(0, len(pdf_urls) - index)
        job.message = (
            f"Downloading PDFs… loaded {job.articles_saved}, {left} left "
            f"of {len(pdf_urls)}."
        )
        if index == 0 or index % 2 == 0:
            await _commit_progress(db, job)
        if delay:
            await asyncio.sleep(delay)
        try:
            status, content, ctype = await fetch(pdf_url)
            if status >= 400:
                job.articles_skipped += 1
                job.error_log = (job.error_log or []) + [f"{pdf_url}: HTTP {status}"]
                continue
            if not _is_pdf_payload(content, ctype) and _is_html_payload(content, ctype):
                html = content.decode("utf-8", errors="ignore")
                nested = [
                    href
                    for href, text in extract_anchors(html, pdf_url)
                    if is_pdf_url(href, text) and _same_host(job.archive_url, href)
                ]
                fetched = False
                for nested_url in nested:
                    nst, nbody, nct = await fetch(nested_url)
                    if nst < 400 and _is_pdf_payload(nbody, nct):
                        pdf_url = nested_url
                        content, ctype = nbody, nct
                        fetched = True
                        break
                if not fetched:
                    job.articles_skipped += 1
                    continue
            if not _is_pdf_payload(content, ctype):
                job.articles_skipped += 1
                continue
            name = pdf_url.rstrip("/").split("/")[-1] or f"article_{index + 1}.pdf"
            if not name.lower().endswith(".pdf"):
                name = f"{name}.pdf" if "." not in name else f"article_{index + 1}.pdf"
            _article, created = await ingest_pdf_bytes(
                db, journal, content, name, source_url=pdf_url
            )
            if created:
                job.articles_saved += 1
            else:
                job.articles_skipped += 1
        except Exception as exc:
            job.articles_skipped += 1
            job.error_log = (job.error_log or []) + [f"{pdf_url}: {exc}"]
    await db.commit()
