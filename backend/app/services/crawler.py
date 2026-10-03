"""Fast OJS archive inventory, then download PDFs only for issues the operator selects."""

from __future__ import annotations

import asyncio
import re
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.database.session import AsyncSessionLocal
from app.models.citation import Article, CrawlJob, Issue, Journal
from app.services.ingest import ingest_pdf_bytes

USER_AGENT = "CitationAssistant/1.0 (journal archive ingest)"
MAX_ARCHIVE_PAGES = 80
ISSUE_CONCURRENCY = 12

ISSUE_VIEW_HREF = re.compile(r"/issue/view/\d+", re.I)
ARCHIVE_HREF = re.compile(r"/issue/archive(?:/\d+)?/?$", re.I)
ARTICLE_VIEW_HREF = re.compile(r"/article/view/(\d+)(?:/(\d+))?", re.I)
ARTICLE_DOWNLOAD_HREF = re.compile(r"/article/download/", re.I)
OJS_ARTICLE_ID = re.compile(r"/article/(?:view|download)/(\d+)", re.I)
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


def _article_id(url: str) -> str | None:
    path = urlparse(url or "").path or ""
    match = ARTICLE_VIEW_HREF.search(path)
    if match:
        return match.group(1)
    match = OJS_ARTICLE_ID.search(path)
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


def _pdf_url_rank(url: str) -> int:
    """Prefer a real download galley over an article landing/view URL."""
    path = (urlparse(url).path or "").lower()
    if "/article/download/" in path:
        return 0
    view = ARTICLE_VIEW_HREF.search(path)
    if view and view.group(2):
        return 1
    if path.endswith(".pdf"):
        return 2
    return 3


def _unique_pdfs_by_article(urls: list[str]) -> list[str]:
    """One PDF URL per OJS article id. Extra galleys are why 'skipped' looked huge."""
    chosen: dict[str, str] = {}
    order: list[str] = []
    no_id: list[str] = []
    seen_plain: set[str] = set()
    for url in urls:
        cleaned = _clean(str(url or ""))
        if not cleaned:
            continue
        aid = _article_id(cleaned)
        if not aid:
            if cleaned not in seen_plain:
                seen_plain.add(cleaned)
                no_id.append(cleaned)
            continue
        current = chosen.get(aid)
        if current is None:
            chosen[aid] = cleaned
            order.append(aid)
        elif _pdf_url_rank(cleaned) < _pdf_url_rank(current):
            chosen[aid] = cleaned
    return [chosen[aid] for aid in order] + no_id


async def _commit_progress(db: AsyncSession, job) -> None:
    await db.commit()
    await db.refresh(job)


def _inventory_message(job: CrawlJob) -> str:
    issues = int(job.issues_found or 0)
    articles = int(job.articles_found or 0)
    return f"Found {issues} issues · {articles} articles. Choose which issues to download."


def _reset_job_counts(job: CrawlJob) -> None:
    job.articles_saved = 0
    job.articles_skipped = 0
    job.articles_already = 0
    job.articles_failed = 0
    job.articles_removed = 0


def _live_article_index(inventory: list[dict]) -> tuple[set[str], set[str], set[str]]:
    ids: set[str] = set()
    pdfs: set[str] = set()
    landings: set[str] = set()
    for row in inventory:
        for url in row.get("pdf_urls") or []:
            cleaned = _clean(str(url or ""))
            if not cleaned:
                continue
            pdfs.add(cleaned)
            aid = _article_id(cleaned)
            if aid:
                ids.add(aid)
        for url in row.get("article_urls") or []:
            cleaned = _clean(str(url or ""))
            if not cleaned:
                continue
            landings.add(cleaned)
            aid = _article_id(cleaned)
            if aid:
                ids.add(aid)
    return ids, pdfs, landings


def _unlink_stored_pdf(path: str | None) -> None:
    if not path:
        return
    stored = Path(path)
    if stored.is_file():
        stored.unlink()


def _article_is_live(article: Article, live_ids: set[str], live_pdfs: set[str], live_landings: set[str]) -> bool:
    url = _clean(article.source_url or "")
    if not url:
        return True
    aid = _article_id(url)
    if aid and aid in live_ids:
        return True
    return url in live_pdfs or url in live_landings


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
            pdfs = list(row.get("pdf_urls") or [])
            article_urls = list(row.get("article_urls") or [])
            if len(pdfs) < max(int(row.get("article_count") or 0), len(article_urls)):
                for art_url in article_urls:
                    aid = _article_id(art_url)
                    if not aid or any(_pdf_covers_article(url, aid) for url in pdfs):
                        continue
                    pdfs.extend(await _pdfs_from_article_page(fetch, art_url, aid, delay))
            pdf_urls.extend(pdfs)
        pdf_urls = _unique_pdfs_by_article(_unique(pdf_urls))
        job.status = "running"
        job.phase = "downloading"
        job.articles_found = len(pdf_urls)
        _reset_job_counts(job)
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
                    f"Done. Loaded {job.articles_saved} new PDFs"
                    + (
                        f", {job.articles_already} already on this server"
                        if job.articles_already
                        else ""
                    )
                    + (
                        f", {job.articles_failed} could not be downloaded"
                        if job.articles_failed
                        else ""
                    )
                    + "."
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


async def run_state_update_job(job_id: int, fetch=default_fetch, delay: float = 0.02) -> None:
    """Re-scan the live journal and make the server archive match it.

    New articles/issues/volumes are ingested. Papers that are no longer listed
    on the journal site are removed. Manual uploads with no source URL are kept.
    """
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
        job.status = "running"
        job.phase = "updating"
        job.started_at = datetime.now(timezone.utc)
        job.finished_at = None
        job.cancel_requested = False
        _reset_job_counts(job)
        job.message = "Reading the live journal archive…"
        await db.commit()
        try:
            await _scan_issues(db, job, fetch, delay)
            if job.cancel_requested:
                job.status = "cancelled"
                job.phase = "cancelled"
                job.message = "State update cancelled."
                job.finished_at = datetime.now(timezone.utc)
                await db.commit()
                return
            inventory = list(job.inventory or [])
            live_ids, live_pdfs, live_landings = _live_article_index(inventory)
            if not live_ids and not live_pdfs:
                job.status = "failed"
                job.phase = "failed"
                job.message = (
                    "State update stopped: the live archive listing was empty, "
                    "so nothing was added or removed."
                )
                job.finished_at = datetime.now(timezone.utc)
                await db.commit()
                return

            local = list(
                (
                    await db.execute(
                        select(Article)
                        .options(selectinload(Article.issue))
                        .join(Issue, Article.issue_id == Issue.id)
                        .where(Issue.journal_id == journal.id)
                    )
                )
                .scalars()
                .all()
            )
            local_ids = {_article_id(a.source_url or "") for a in local}
            local_ids.discard(None)
            local_urls = {_clean(a.source_url or "") for a in local}
            live_pdf_list = _unique_pdfs_by_article(sorted(live_pdfs))
            to_fetch = [
                url
                for url in live_pdf_list
                if (_article_id(url) not in local_ids) and (url not in local_urls)
            ]
            already_here = max(0, len(live_pdf_list) - len(to_fetch))
            job.phase = "downloading"
            job.articles_found = len(live_pdf_list)
            job.articles_already = already_here
            job.articles_skipped = already_here
            job.message = (
                f"Live archive has {len(live_ids)} articles. "
                f"{already_here} already on this server. "
                f"Downloading {len(to_fetch)} missing PDF(s)…"
            )
            await db.commit()
            if to_fetch:
                await _download_pdfs(db, job, journal, to_fetch, fetch, delay)

            local = list(
                (
                    await db.execute(
                        select(Article)
                        .options(selectinload(Article.issue))
                        .join(Issue, Article.issue_id == Issue.id)
                        .where(Issue.journal_id == journal.id)
                    )
                )
                .scalars()
                .all()
            )
            removed = 0
            if not job.cancel_requested:
                job.phase = "updating"
                job.message = "Removing papers that are no longer on the journal site…"
                await db.commit()
                for article in local:
                    if _article_is_live(article, live_ids, live_pdfs, live_landings):
                        continue
                    _unlink_stored_pdf(article.pdf_path)
                    await db.delete(article)
                    removed += 1
                job.articles_removed = removed
                await db.flush()
                issues = list(
                    (
                        await db.execute(select(Issue).where(Issue.journal_id == journal.id))
                    )
                    .scalars()
                    .all()
                )
                for issue in issues:
                    remaining = int(
                        (
                            await db.execute(
                                select(func.count(Article.id)).where(Article.issue_id == issue.id)
                            )
                        ).scalar()
                        or 0
                    )
                    if remaining == 0:
                        await db.delete(issue)

            if job.cancel_requested:
                job.status = "cancelled"
                job.phase = "cancelled"
                job.message = (
                    f"State update cancelled. Added {job.articles_saved}, "
                    f"removed {job.articles_removed}."
                )
            else:
                job.status = "completed"
                job.phase = "completed"
                job.message = (
                    f"Archive state updated. Added {job.articles_saved} new paper(s). "
                    f"{job.articles_already} already on this server. "
                    f"Removed {job.articles_removed} no longer listed on the journal site"
                    + (
                        f". {job.articles_failed} could not be downloaded"
                        if job.articles_failed
                        else ""
                    )
                    + "."
                )
                for row in inventory:
                    row["downloaded"] = True
                job.inventory = inventory
                flag_modified(job, "inventory")
        except Exception as exc:
            job.status = "failed"
            job.phase = "failed"
            job.message = f"State update failed: {exc}"
            job.error_log = (job.error_log or []) + [str(exc)]
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()


async def _scan_issues(db: AsyncSession, job, fetch, delay: float) -> None:
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
    pdf_urls: list[str],
    fetch,
    delay: float,
) -> None:
    seen_aids: set[str] = set()
    for index, pdf_url in enumerate(pdf_urls):
        if job.cancel_requested:
            return
        aid = _article_id(pdf_url)
        if aid and aid in seen_aids:
            job.articles_already += 1
            job.articles_skipped += 1
            continue
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
                job.articles_failed += 1
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
                    job.articles_failed += 1
                    job.articles_skipped += 1
                    continue
            if not _is_pdf_payload(content, ctype):
                job.articles_failed += 1
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
                job.articles_already += 1
                job.articles_skipped += 1
            if aid:
                seen_aids.add(aid)
        except Exception as exc:
            job.articles_failed += 1
            job.articles_skipped += 1
            job.error_log = (job.error_log or []) + [f"{pdf_url}: {exc}"]
    await db.commit()
