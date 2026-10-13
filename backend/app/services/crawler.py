"""Fast OJS archive inventory, then download PDFs for every issue (retries stay selectable)."""

from __future__ import annotations

import asyncio
import re
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database.session import AsyncSessionLocal
from app.models.citation import CrawlJob, Journal
from app.services.citation_parser import parse_volume_issue
from app.services.ingest import ingest_pdf_bytes

USER_AGENT = "CitationAssistant/1.0 (journal archive ingest)"
MAX_ARCHIVE_PAGES = 80
ISSUE_CONCURRENCY = 12
FETCH_TIMEOUT = httpx.Timeout(90.0, connect=20.0)
FETCH_RETRIES = 3

ISSUE_VIEW_HREF = re.compile(r"/issue/view/(\d+)", re.I)
ARCHIVE_HREF = re.compile(r"/issue/archive", re.I)
ARTICLE_VIEW_HREF = re.compile(r"/article/view/(\d+)(?:/(\d+))?", re.I)
ARTICLE_DOWNLOAD_HREF = re.compile(r"/article/download/", re.I)
VOL_ISSUE_HREF = re.compile(
    r"Vol\.?\s*(\d+)\s*(?:No\.?|Issue)\s*(\d+)(?:\s*\((\d{4})\))?",
    re.I,
)
CITATION_VOL_META = re.compile(
    r'<meta\b[^>]*\bname=["\']citation_volume["\'][^>]*\bcontent=["\'](\d+)["\']',
    re.I,
)
CITATION_ISSUE_META = re.compile(
    r'<meta\b[^>]*\bname=["\']citation_issue["\'][^>]*\bcontent=["\'](\d+)["\']',
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


def _host(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname[4:] if hostname.startswith("www.") else hostname


def _same_host(root: str, url: str) -> bool:
    return bool(_host(root) and _host(root) == _host(url))


def _clean(url: str) -> str:
    parsed = urlparse(urldefrag(url)[0].strip())
    path = re.sub(r"/{2,}", "/", parsed.path or "")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse(parsed._replace(path=path, fragment=""))


def _issue_key(url: str) -> str:
    parsed = urlparse(_clean(url))
    match = ISSUE_VIEW_HREF.search(parsed.path or "")
    if not match:
        return _clean(url)
    path = re.sub(r"/issue/view/\d+.*", f"/issue/view/{match.group(1)}", parsed.path or "", flags=re.I)
    return urlunparse(parsed._replace(path=path, query="", fragment=""))


def _next_archive_page(url: str) -> str | None:
    parsed = urlparse(_clean(url))
    path = parsed.path or ""
    match = re.search(r"^(?P<prefix>/.*/issue/archive)(?:/(?P<n>\d+))?$", path, re.I)
    if not match:
        if re.search(r"/issue/archive$", path, re.I):
            return urlunparse(parsed._replace(path=f"{path}/2", query=""))
        return None
    prefix = match.group("prefix")
    number = int(match.group("n") or 1)
    return urlunparse(parsed._replace(path=f"{prefix}/{number + 1}", query=""))


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


def _article_id(url: str) -> str | None:
    match = ARTICLE_VIEW_HREF.search(urlparse(url).path or "")
    return match.group(1) if match else None


def _article_landing_url(url: str, article_id: str | None = None) -> str:
    parsed = urlparse(_clean(url))
    path = parsed.path or ""
    match = ARTICLE_VIEW_HREF.search(path)
    aid = article_id or (match.group(1) if match else None)
    if not aid:
        return _clean(url)
    path = re.sub(r"/article/view/\d+(?:/\d+)?", f"/article/view/{aid}", path, count=1, flags=re.I)
    return _clean(urlunparse(parsed._replace(path=path, query="", fragment="")))


def _citation_pdf_urls(html: str, base: str) -> list[str]:
    found: list[str] = []
    patterns = (
        re.compile(
            r'<meta\b[^>]*\bname=["\']citation_pdf_url["\'][^>]*\bcontent=["\']([^"\']+)["\']',
            re.I,
        ),
        re.compile(
            r'<meta\b[^>]*\bcontent=["\']([^"\']+)["\'][^>]*\bname=["\']citation_pdf_url["\']',
            re.I,
        ),
    )
    for pattern in patterns:
        for match in pattern.finditer(html or ""):
            found.append(_clean(urljoin(base, match.group(1))))
    return found


def _pdfs_for_article(html: str, page_url: str, article_id: str | None = None) -> list[str]:
    """PDFs that belong to this article — ignore related-article links on the same page."""
    pdfs = _citation_pdf_urls(html, page_url)
    for href, text in extract_anchors(html, page_url):
        path = urlparse(href).path or ""
        view = ARTICLE_VIEW_HREF.search(path)
        if article_id:
            if view and view.group(1) != article_id:
                continue
            download = re.search(r"/article/download/(\d+)", path, re.I)
            if download and download.group(1) != article_id:
                continue
        if is_pdf_url(href, text) or (view and view.group(2)):
            pdfs.append(_clean(href))
    return _unique(pdfs)


def _pdf_covers_article(pdf_url: str, article_id: str) -> bool:
    path = urlparse(pdf_url).path or ""
    view = ARTICLE_VIEW_HREF.search(path)
    if view and view.group(1) == article_id:
        return True
    return bool(re.search(rf"/article/download/{re.escape(article_id)}(?:/|$)", path, re.I))


async def _pdfs_from_article_page(fetch, url: str, article_id: str, delay: float) -> list[str]:
    if delay:
        await asyncio.sleep(delay)
    try:
        status, body, ctype = await fetch(url)
    except Exception:
        return []
    if status >= 400:
        return []
    if _is_pdf_payload(body, ctype):
        return [_clean(url)]
    if not _is_html_payload(body, ctype):
        return []
    html = body.decode("utf-8", errors="ignore")
    return _pdfs_for_article(html, url, article_id)


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
    last_error: Exception | None = None
    for attempt in range(FETCH_RETRIES):
        try:
            async with httpx.AsyncClient(
                timeout=FETCH_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                resp = await client.get(url)
                if resp.status_code in {429, 502, 503, 504} and attempt + 1 < FETCH_RETRIES:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                return resp.status_code, resp.content, resp.headers.get("content-type") or ""
        except Exception as exc:
            last_error = exc
            if attempt + 1 < FETCH_RETRIES:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            raise
    if last_error:
        raise last_error
    return 599, b"", ""


def _is_pdf_payload(content: bytes, content_type: str) -> bool:
    return content[:5] == b"%PDF-" or "pdf" in (content_type or "").lower()


def _is_html_payload(content: bytes, content_type: str) -> bool:
    ctype = (content_type or "").lower()
    if "html" in ctype or "xml" in ctype:
        return True
    head = content[:200].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _parse_vol_issue(text: str) -> tuple[int | None, int | None, int | None]:
    volume, number, year = parse_volume_issue(text or "")
    if volume and number:
        return volume, number, year
    match = VOL_ISSUE_HREF.search(text or "")
    if not match:
        return volume, number, year
    parsed_year = int(match.group(3)) if match.group(3) else year
    return int(match.group(1)), int(match.group(2)), parsed_year


def _heading_from_html(html: str) -> tuple[int | None, int | None, int | None]:
    volume, number, year = _parse_vol_issue(html)
    if volume and number:
        return volume, number, year
    meta_vol = CITATION_VOL_META.search(html or "")
    meta_iss = CITATION_ISSUE_META.search(html or "")
    if meta_vol and meta_iss:
        return int(meta_vol.group(1)), int(meta_iss.group(1)), year
    return volume, number, year


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


async def run_crawl_job(
    job_id: int,
    fetch=default_fetch,
    delay: float = 0.0,
    auto_download: bool = False,
) -> None:
    """Scan every archive page. Optionally download every discovered issue in the same job."""
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
            elif auto_download:
                issue_urls = [
                    str(row.get("url") or "")
                    for row in (job.inventory or [])
                    if row.get("url")
                ]
                if issue_urls:
                    await _download_selected(db, job, journal, issue_urls, fetch, delay)
                else:
                    job.status = "completed"
                    job.phase = "completed"
                    job.message = "Scan finished. No issues were listed."
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
        try:
            await _download_selected(db, job, journal, issue_urls, fetch, delay)
        except Exception as exc:
            job.status = "failed"
            job.phase = "failed"
            job.message = f"Download failed: {exc}"
            job.error_log = (job.error_log or []) + [str(exc)]
            job.finished_at = datetime.now(timezone.utc)
        await db.commit()


async def _download_selected(
    db: AsyncSession,
    job: CrawlJob,
    journal: Journal,
    issue_urls: list[str],
    fetch,
    delay: float,
) -> None:
    inventory = list(job.inventory or [])
    selected = {_issue_key(url) for url in issue_urls if url}
    chosen = [row for row in inventory if _issue_key(str(row.get("url") or "")) in selected]
    items: list[dict] = []
    seen_pdfs: set[str] = set()
    for row in chosen:
        pdfs = list(row.get("pdf_urls") or [])
        article_urls = list(row.get("article_urls") or [])
        if len(pdfs) < max(int(row.get("article_count") or 0), len(article_urls)):
            for art_url in article_urls:
                aid = _article_id(art_url)
                if not aid or any(_pdf_covers_article(url, aid) for url in pdfs):
                    continue
                pdfs.extend(await _pdfs_from_article_page(fetch, art_url, aid, delay))
        pdfs = _unique(pdfs)
        row["pdf_urls"] = pdfs
        for pdf_url in pdfs:
            key = _clean(pdf_url)
            if key in seen_pdfs:
                continue
            seen_pdfs.add(key)
            items.append(
                {
                    "url": pdf_url,
                    "volume": row.get("volume"),
                    "issue_number": row.get("issue_number"),
                    "year": row.get("year"),
                }
            )
    job.status = "running"
    job.phase = "downloading"
    job.articles_found = len(items)
    job.articles_saved = 0
    job.articles_skipped = 0
    job.cancel_requested = False
    job.finished_at = None
    job.message = f"Downloading {len(items)} PDFs from {len(chosen)} issue(s)…"
    flag_modified(job, "inventory")
    await db.commit()
    await _download_pdfs(db, job, journal, items, fetch, delay)
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
            if _issue_key(str(row.get("url") or "")) in selected:
                row["downloaded"] = True
        job.inventory = inventory
        flag_modified(job, "inventory")
    job.finished_at = datetime.now(timezone.utc)


async def _scan_issues(db: AsyncSession, job: CrawlJob, fetch, delay: float) -> None:
    archive = _clean(job.archive_url)
    queue: deque[str] = deque([archive])
    next_page = _next_archive_page(archive)
    if next_page:
        queue.append(next_page)
    seen_pages: set[str] = set()
    issues: dict[str, dict] = {}
    empty_archive_pages = 0

    while queue and len(seen_pages) < MAX_ARCHIVE_PAGES:
        if job.cancel_requested:
            return
        page_url = _clean(queue.popleft())
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
            job.error_log = (job.error_log or []) + [
                f"{page_url}: HTTP {status}" if status >= 400 else f"{page_url}: not HTML"
            ]
            continue
        html = body.decode("utf-8", errors="ignore")
        new_issues = 0
        for href, text in extract_anchors(html, page_url):
            if not href or not _same_host(archive, href):
                continue
            href = _clean(href)
            path = urlparse(href).path or ""
            if SKIP_PATH.search(path) or SKIP_EXT.search(path):
                continue
            if ARCHIVE_HREF.search(path) and href not in seen_pages:
                queue.append(href)
            if ISSUE_VIEW_HREF.search(href):
                key = _issue_key(href)
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
                    new_issues += 1
                elif title and len(title) > len(str(issues[key].get("title") or "")):
                    issues[key]["title"] = title
                    if volume:
                        issues[key]["volume"] = volume
                        issues[key]["issue_number"] = number
                        issues[key]["year"] = year
        if ARCHIVE_HREF.search(urlparse(page_url).path or ""):
            if new_issues == 0 and page_url != archive:
                empty_archive_pages += 1
            else:
                empty_archive_pages = 0
                nxt = _next_archive_page(page_url)
                if nxt and nxt not in seen_pages and empty_archive_pages < 2:
                    queue.append(nxt)
        if empty_archive_pages >= 2:
            queue = deque(
                url for url in queue if not ARCHIVE_HREF.search(urlparse(url).path or "") or url in seen_pages
            )

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
            heading = _heading_from_html(html)
            if heading[0] and (not row.get("volume") or not row.get("issue_number")):
                row["volume"] = heading[0] or row.get("volume")
                row["issue_number"] = heading[1] or row.get("issue_number")
                row["year"] = heading[2] or row.get("year")
            article_ids: list[str] = []
            seen_ids: set[str] = set()
            article_urls: dict[str, str] = {}
            pdfs: list[str] = []
            for href, text in extract_anchors(html, row["url"]):
                if not _same_host(archive, href):
                    continue
                match = ARTICLE_VIEW_HREF.search(href)
                if match:
                    aid = match.group(1)
                    if aid not in seen_ids:
                        seen_ids.add(aid)
                        article_ids.append(aid)
                        article_urls[aid] = _article_landing_url(href, aid)
                    if match.group(2) or is_pdf_url(href, text):
                        pdfs.append(_clean(href))
                elif is_pdf_url(href, text):
                    pdfs.append(_clean(href))
            pdfs = _unique(pdfs)
            for aid in article_ids:
                if any(_pdf_covers_article(url, aid) for url in pdfs):
                    continue
                landing = article_urls.get(aid)
                if not landing:
                    continue
                pdfs.extend(await _pdfs_from_article_page(fetch, landing, aid, delay))
            row["article_urls"] = [article_urls[aid] for aid in article_ids]
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
    items: list[dict],
    fetch,
    delay: float,
) -> None:
    inventory = list(job.inventory or [])
    for index, item in enumerate(items):
        if job.cancel_requested:
            return
        pdf_url = str(item.get("url") or "")
        left = max(0, len(items) - index)
        job.message = (
            f"Downloading PDFs… loaded {job.articles_saved}, {left} left "
            f"of {len(items)}."
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
                aid = _article_id(pdf_url)
                nested = [
                    href
                    for href in _pdfs_for_article(html, pdf_url, aid)
                    if _same_host(job.archive_url, href)
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
                    job.error_log = (job.error_log or []) + [f"{item.get('url')}: no PDF on article page"]
                    continue
            if not _is_pdf_payload(content, ctype):
                job.articles_skipped += 1
                job.error_log = (job.error_log or []) + [f"{pdf_url}: not a PDF"]
                continue
            name = pdf_url.rstrip("/").split("/")[-1] or f"article_{index + 1}.pdf"
            if not name.lower().endswith(".pdf"):
                name = f"{name}.pdf" if "." not in name else f"article_{index + 1}.pdf"
            _article, created = await ingest_pdf_bytes(
                db,
                journal,
                content,
                name,
                source_url=pdf_url,
                volume=item.get("volume"),
                issue_number=item.get("issue_number"),
                year=item.get("year"),
                inventory=inventory,
            )
            if created:
                job.articles_saved += 1
            else:
                job.articles_skipped += 1
        except Exception as exc:
            job.articles_skipped += 1
            job.error_log = (job.error_log or []) + [f"{pdf_url}: {exc}"]
    await db.commit()
