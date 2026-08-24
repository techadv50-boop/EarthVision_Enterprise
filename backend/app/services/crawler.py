"""Recursively crawl a journal archive (folders + OJS pages) and ingest every PDF."""

from __future__ import annotations

import asyncio
import re
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import AsyncSessionLocal
from app.models.citation import CrawlJob, Journal
from app.services.ingest import ingest_pdf_bytes

USER_AGENT = "CitationAssistant/1.0 (journal archive ingest)"
MAX_PAGES = 8000

ISSUE_HREF = re.compile(r"/issue/view/\d+", re.I)
ARTICLE_GALLEY_HREF = re.compile(r"/article/view/\d+/\d+", re.I)
ARTICLE_DOWNLOAD_HREF = re.compile(r"/article/download/", re.I)

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


def _journal_prefix(archive: str) -> str:
    path = urlparse(archive).path or "/"
    match = re.search(r"(.*?/index\.php/[^/]+)", path, re.I)
    if match:
        return match.group(1).rstrip("/")
    if path.rstrip("/").endswith("/archive"):
        return path[: path.lower().rfind("/archive")].rstrip("/") or "/"
    if path.endswith("/"):
        return path.rstrip("/") or "/"
    return path.rsplit("/", 1)[0] or "/"


def _in_scope(archive: str, url: str) -> bool:
    if not _same_host(archive, url):
        return False
    path = urlparse(url).path or "/"
    if SKIP_PATH.search(path):
        return False
    prefix = _journal_prefix(archive)
    if prefix and (path == prefix or path.startswith(prefix + "/")):
        return True
    lowered = path.lower()
    return any(
        token in lowered
        for token in ("/issue/", "/article/", "/download", "/galley", "/archive", "/files/", "/pdf")
    )


def is_pdf_url(url: str, link_text: str = "") -> bool:
    path = (urlparse(url).path or "").lower()
    if path.endswith(".pdf") or ".pdf?" in url.lower():
        return True
    if ARTICLE_DOWNLOAD_HREF.search(path) or "/download/" in path:
        return True
    if ARTICLE_GALLEY_HREF.search(path):
        return True
    if "galley" in path and "pdf" in (path + " " + (link_text or "").lower()):
        return True
    if PDF_LINK_TEXT.match(link_text or ""):
        return True
    return False


def _should_skip_href(url: str) -> bool:
    if not url or url.startswith(("mailto:", "javascript:", "tel:", "data:")):
        return True
    path = urlparse(url).path or ""
    return bool(SKIP_EXT.search(path) or SKIP_PATH.search(path))


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
        timeout=40.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:
        resp = await client.get(url)
        return resp.status_code, resp.content, resp.headers.get("content-type") or ""


def _robots_allows(robots_txt: str, path: str) -> bool:
    """Honor Disallow lines for a generic User-agent: * block."""
    in_star = False
    for raw in robots_txt.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lower = line.lower()
        if lower.startswith("user-agent:"):
            in_star = "*" in line.split(":", 1)[-1]
            continue
        if in_star and lower.startswith("disallow:"):
            rule = line.split(":", 1)[-1].strip()
            if rule and path.startswith(rule):
                return False
    return True


def _is_pdf_payload(content: bytes, content_type: str) -> bool:
    return content[:5] == b"%PDF-" or "pdf" in (content_type or "").lower()


def _is_html_payload(content: bytes, content_type: str) -> bool:
    ctype = (content_type or "").lower()
    if "html" in ctype or "xml" in ctype:
        return True
    head = content[:200].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _remaining(job: CrawlJob) -> int:
    return max(
        0,
        int(job.articles_found or 0)
        - int(job.articles_saved or 0)
        - int(job.articles_skipped or 0),
    )


def _scan_message(pages: int, pdfs: int) -> str:
    return f"Scanning folders… {pages} pages opened, {pdfs} PDF files found so far"


def _download_message(job: CrawlJob) -> str:
    found = int(job.articles_found or 0)
    saved = int(job.articles_saved or 0)
    left = _remaining(job)
    return f"Found {found} PDF files. Loaded {saved}, {left} left."


async def _commit_progress(db: AsyncSession, job: CrawlJob) -> None:
    await db.commit()
    await db.refresh(job)


async def run_crawl_job(job_id: int, fetch=default_fetch, delay: float = 0.05) -> None:
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
        job.message = "Scanning archive folders for PDF files…"
        job.started_at = datetime.now(timezone.utc)
        job.error_log = list(job.error_log or [])
        await db.commit()
        try:
            await _crawl(db, job, journal, fetch, delay)
            if job.cancel_requested:
                job.status = "cancelled"
                job.phase = "cancelled"
                job.message = (
                    f"Cancelled after finding {job.articles_found} PDFs. "
                    f"Loaded {job.articles_saved}, {_remaining(job)} left."
                )
            else:
                job.status = "completed"
                job.phase = "completed"
                job.message = (
                    f"Done. Found {job.articles_found} PDF files, "
                    f"loaded {job.articles_saved}, skipped {job.articles_skipped}."
                )
        except Exception as exc:
            job.status = "failed"
            job.phase = "failed"
            job.message = f"Crawl failed: {exc}"
            job.error_log = (job.error_log or []) + [str(exc)]
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()


async def _crawl(
    db: AsyncSession, job: CrawlJob, journal: Journal, fetch, delay: float
) -> None:
    archive = job.archive_url
    parsed = urlparse(archive)
    robots_txt = ""
    try:
        rst, rbody, _rct = await fetch(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
        if rst < 400:
            robots_txt = rbody.decode("utf-8", errors="ignore")
    except Exception:
        robots_txt = ""

    queue: deque[str] = deque([_clean(archive)])
    seen_pages: set[str] = set()
    pdf_urls: list[str] = []
    seen_pdfs: set[str] = set()

    def remember_pdf(url: str) -> None:
        clean = _clean(url)
        if not clean or clean in seen_pdfs:
            return
        if robots_txt and not _robots_allows(robots_txt, urlparse(clean).path):
            return
        seen_pdfs.add(clean)
        pdf_urls.append(clean)

    while queue and len(seen_pages) < MAX_PAGES:
        if job.cancel_requested:
            return
        page_url = queue.popleft()
        if page_url in seen_pages:
            continue
        seen_pages.add(page_url)
        job.pages_crawled = len(seen_pages)
        if ISSUE_HREF.search(page_url):
            job.issues_found = (job.issues_found or 0) + 1
        job.articles_found = len(pdf_urls)
        job.message = _scan_message(len(seen_pages), len(pdf_urls))
        if len(seen_pages) == 1 or len(seen_pages) % 5 == 0:
            await _commit_progress(db, job)

        await asyncio.sleep(delay)
        try:
            status, body, ctype = await fetch(page_url)
        except Exception as exc:
            job.error_log = (job.error_log or []) + [f"{page_url}: {exc}"]
            continue
        if status >= 400:
            job.error_log = (job.error_log or []) + [f"{page_url}: HTTP {status}"]
            continue
        if _is_pdf_payload(body, ctype):
            remember_pdf(page_url)
            continue
        if not _is_html_payload(body, ctype):
            continue
        html = body.decode("utf-8", errors="ignore")
        for href, text in extract_anchors(html, page_url):
            if _should_skip_href(href) or not _same_host(archive, href):
                continue
            if is_pdf_url(href, text):
                remember_pdf(href)
                continue
            if not _in_scope(archive, href):
                continue
            if href not in seen_pages:
                queue.append(href)

    job.pages_crawled = len(seen_pages)
    job.issues_found = job.issues_found or sum(
        1 for url in seen_pages if ISSUE_HREF.search(url)
    )
    job.articles_found = len(pdf_urls)
    job.phase = "downloading"
    job.message = (
        f"Found {len(pdf_urls)} PDF files in total. Loading…"
        if pdf_urls
        else "No PDF files found in this archive."
    )
    await _commit_progress(db, job)

    for index, pdf_url in enumerate(pdf_urls):
        if job.cancel_requested:
            return
        job.message = _download_message(job)
        await _commit_progress(db, job)
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
                    if is_pdf_url(href, text) and _same_host(archive, href)
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

    job.message = _download_message(job)
    await db.commit()
