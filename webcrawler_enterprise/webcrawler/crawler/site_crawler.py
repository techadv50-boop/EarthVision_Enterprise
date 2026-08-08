"""High-speed full-site crawler: concurrent HTTP first, Playwright fallback."""

from __future__ import annotations

import gc
import heapq
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from webcrawler.db.duplicates import DuplicateManager
from webcrawler.db.frontier import FrontierStore
from webcrawler.downloader.file_downloader import FileDownloader
from webcrawler.extractors.email import extract_emails_from_file
from webcrawler.extractors.phone import extract_phones_from_file, region_from_url
from webcrawler.logger.crawl_logger import CrawlLogger
from webcrawler.parser.html_parser import HtmlParser
from webcrawler.queue.manager import QueueItem
from webcrawler.settings.manager import AppSettings
from webcrawler.utils.folders import ensure_site_structure, html_mirror_path, site_folder
from webcrawler.utils.network import is_connectivity_error, is_online
from webcrawler.utils.url import (
    download_url_from_galley_view,
    galley_view_from_download_url,
    is_document_url,
    is_image_url,
    looks_like_document_path,
    normalize_url,
    same_site,
)

CONTACT_HINTS = (
    "contact",
    "faculty",
    "staff",
    "directory",
    "people",
    "about",
    "department",
    "office",
    "phone",
    "email",
    "personnel",
    "team",
    "admissions",
    "registrar",
    "faculty-staff",
    "telephone",
)

SEED_PATHS = (
    "/contact",
    "/contact-us",
    "/contact-list",
    "/contacts",
    "/about",
    "/about-us",
    "/faculty",
    "/staff",
    "/directory",
    "/admissions",
    "/admissions/contact",
    # Journal / OJS discovery (issues → articles → PDF downloads)
    "/issue/archive",
    "/issue/current",
    "/articles",
    "/archives",
    "/index.php/hi/issue/archive",
    "/index.php/index/issue/archive",
)


@dataclass
class SiteResult:
    website: str
    domain: str
    pages_crawled: int = 0
    documents_downloaded: int = 0
    pdfs: int = 0
    word_files: int = 0
    excel_files: int = 0
    powerpoint_files: int = 0
    images: int = 0
    emails: int = 0
    phones: int = 0
    start_time: str = ""
    end_time: str = ""
    processing_time: str = ""
    status: str = "Completed"
    error: str | None = None
    site_dir: Path | None = None
    emails_list: list[str] = field(default_factory=list)
    phones_list: list[str] = field(default_factory=list)


ProgressCallback = Callable[[dict], None]
ControlFlag = Callable[[], str]


# Journal content must outrank citation-style / UI chrome links.
JOURNAL_PRIORITY_MARKERS = (
    "/article/view/",
    "/article/download/",
    "/issue/view/",
    "/issue/archive",
    "/issue/current",
)

# Do not waste crawl budget on OJS chrome / export endpoints.
SKIP_URL_MARKERS = (
    "citationstylelanguage",
    "/login",
    "/user/register",
    "/user/home",
    "/user/profile",
    "return=json",
    "/gateway/plugin/webfeed",
    "/$$$call$$$",
    "/api/v1/",
    "/notification/",
    "/rt/",
    "/about/submissions",
)


def _is_priority_url(url: str) -> bool:
    return _url_priority_rank(url) <= 5


def _url_priority_rank(url: str) -> int:
    """Lower number = crawl sooner (deep PDF/galley before abstracts/chrome)."""
    path = urlparse(url or "").path.lower()
    if looks_like_document_path(url) or "/article/download/" in path:
        return 0
    if re.search(r"/article/view/\d+/\d+", path):
        return 1  # deep galley HTML
    if re.search(r"/article/view/\d+/?$", path):
        return 2  # article abstract
    if "/issue/view/" in path:
        return 3
    if "/issue/archive" in path or "/issue/current" in path:
        return 4
    if any(hint in path for hint in CONTACT_HINTS):
        return 5
    if any(marker in path for marker in JOURNAL_PRIORITY_MARKERS):
        return 4
    return 6


def _should_skip_crawl_url(url: str) -> bool:
    raw = (url or "").lower()
    return any(marker in raw for marker in SKIP_URL_MARKERS)


def _galley_view_from_download(url: str) -> str | None:
    """Map /article/download/{article}/{galley}[/file] → /article/view/{article}/{galley}."""
    return galley_view_from_download_url(url)


def _download_from_galley_view(url: str) -> str | None:
    """Map PDF-button /article/view/{article}/{galley} → /article/download/{article}/{galley}."""
    return download_url_from_galley_view(url)


def _looks_thin(html: str) -> bool:
    if not html or len(html) < 400:
        return True
    if not re.search(r"<body", html, re.I):
        return True
    # SPA shells often have almost no text
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return len(text) < 80


class SiteCrawler:
    """Download every reachable page/document/image as fast as possible without skipping."""

    def __init__(
        self,
        item: QueueItem,
        settings: AppSettings,
        duplicates: DuplicateManager,
        logger: CrawlLogger,
        on_progress: ProgressCallback | None = None,
        control_state: ControlFlag | None = None,
        resume_mode: bool = False,
    ) -> None:
        self.item = item
        self.settings = settings
        self.duplicates = duplicates
        self.logger = logger
        self.on_progress = on_progress
        self.control_state = control_state or (lambda: "running")
        self.resume_mode = resume_mode
        self.parser = HtmlParser()
        # Heap items: (priority_rank, seq, depth, url) — lower rank first, FIFO within rank.
        self._page_heap: list[tuple[int, int, int, str]] = []
        self._queue_seq = 0
        self._queued: set[str] = set()
        self._playwright_queue: deque[tuple[str, int]] = deque()
        self._lock = threading.Lock()
        self._robots: RobotFileParser | None = None
        self._phone_region = region_from_url(item.url)
        self._site_dir: Path | None = None
        self._flush_counter = 0
        self._pages_index: list[str] = []
        self._download_futures: set = set()
        self._heartbeat_at = 0.0
        self._processed_since_gc = 0
        self._consecutive_network_errors = 0
        self._frontier = FrontierStore(self.duplicates.db, item.id)
        self._deep_mode = bool(
            settings.contact_scan_only or settings.download_complete_site
        )

    def crawl(self) -> SiteResult:
        start = datetime.now(timezone.utc)
        site_dir = ensure_site_structure(site_folder(self.item.output_root, self.item.url))
        self._site_dir = site_dir
        self.logger.set_path(site_dir / "Logs" / "crawl_log.txt")
        mode = "LIGHT contact-scan" if self.settings.contact_scan_only else "FULL download"
        self.logger.info(f"Starting {mode} crawl of {self.item.url}")
        self.logger.info(
            f"Workers: pages={self.settings.page_workers}, "
            f"downloads={self.settings.worker_threads}, region={self._phone_region}, "
            f"contact_scan_only={self.settings.contact_scan_only}"
        )
        if self.settings.contact_scan_only:
            self.logger.info(
                "Light mode: every page/PDF/doc is read for emails & phones; "
                "files are NOT saved to disk"
            )

        # Resume continues saved progress. Start always begins the listed site from scratch.
        if self.resume_mode and not self.settings.fresh_site_crawl:
            restored = self._restore_frontier_from_db()
            if self.duplicates.visited_count or restored:
                self.logger.info(
                    f"Resuming site: visited={self.duplicates.visited_count}, "
                    f"frontier_restored={restored}"
                )
        else:
            if self.duplicates.visited_count:
                self.duplicates.clear_crawl_state(clear_contacts=True)
            self._frontier.clear()
            self.logger.info("Starting site from scratch")

        result = SiteResult(
            website=self.item.url,
            domain=self.item.domain,
            start_time=start.isoformat(),
            site_dir=site_dir,
        )

        downloader = FileDownloader(
            site_dir=site_dir,
            settings=self.settings,
            duplicates=self.duplicates,
            logger=self.logger,
            phone_region=self._phone_region,
        )

        def _on_download(url: str, path: str) -> None:
            if path:
                for email in extract_emails_from_file(Path(path)):
                    self.duplicates.add_email(email)
                for phone in extract_phones_from_file(
                    Path(path), default_region=self._phone_region
                ):
                    self.duplicates.add_phone(phone)
            # Record scanned document URLs so depth/coverage is visible in pages_index.
            if self._site_dir is not None:
                self._append_pages_index(url, None, self._site_dir)
            # Also crawl the HTML galley page for the same article/galley ids.
            galley = _galley_view_from_download(url)
            if galley:
                self._enqueue(galley, 1, priority=True)
            self._flush_contacts()
            self._emit_progress(
                current_download=url,
                documents=downloader.stats["documents"],
                emails=len(self.duplicates.emails),
                phones=len(self.duplicates.phones),
            )

        downloader.on_download = _on_download

        root = normalize_url(self.item.url)
        # Always ensure seeds/sitemaps are present; already-visited URLs are skipped later.
        self._enqueue(root, 0, priority=True)
        self._seed_contact_paths(root)
        self._seed_journal_paths(root)
        self._load_robots(root)
        self._load_sitemaps(root)
        self._seed_oai_records(root)
        if not self._wait_until_online():
            result.status = "Cancelled"
            result.error = "Stopped while waiting for internet"
            return self._finalize_result(result, start, downloader, site_dir)

        try:
            self._run_fast_crawl(site_dir, downloader, result)
            if result.status != "Cancelled":
                result.status = "Completed"
                # Site finished cleanly — frontier no longer needed.
                self._frontier.clear()
        except Exception as exc:
            # Keep frontier so the site can resume after crash/power loss.
            result.status = "Failed"
            result.error = str(exc)
            self.logger.error(f"Site crawl failed (progress saved for resume): {exc}")

        return self._finalize_result(result, start, downloader, site_dir)

    def _finalize_result(
        self,
        result: SiteResult,
        start: datetime,
        downloader: FileDownloader,
        site_dir: Path,
    ) -> SiteResult:
        if not self.settings.contact_scan_only:
            try:
                self._rescan_all_downloaded_files(site_dir)
            except Exception as exc:
                self.logger.error(f"Final rescan error: {exc}")
        self._write_pages_index(site_dir)
        self._flush_contacts(force=True)

        emails = sorted(self.duplicates.emails)
        phones = sorted(self.duplicates.phones)
        end = datetime.now(timezone.utc)
        result.end_time = end.isoformat()
        result.processing_time = str(end - start).split(".")[0]
        result.pages_crawled = self.duplicates.visited_count
        result.documents_downloaded = downloader.stats["documents"]
        result.pdfs = downloader.stats["pdfs"]
        result.word_files = downloader.stats["word"]
        result.excel_files = downloader.stats["excel"]
        result.powerpoint_files = downloader.stats["powerpoint"]
        result.images = downloader.stats["images"]
        result.emails = len(emails)
        result.phones = len(phones)
        result.emails_list = emails
        result.phones_list = phones
        result.site_dir = site_dir

        try:
            self._frontier.flush()
        except Exception:
            pass
        self.logger.info(
            f"Finished {self.item.url}: pages={result.pages_crawled} "
            f"docs={result.documents_downloaded} emails={result.emails} phones={result.phones} "
            f"status={result.status} time={result.processing_time} "
            f"frontier_left={self._frontier.count()}"
        )
        self._emit_progress(
            pages=result.pages_crawled,
            documents=result.documents_downloaded,
            emails=result.emails,
            phones=result.phones,
            current_page="",
            current_download="",
        )
        return result

    def _run_fast_crawl(
        self,
        site_dir: Path,
        downloader: FileDownloader,
        result: SiteResult,
    ) -> None:
        page_workers = max(2, min(self.settings.page_workers, 48))
        download_workers = max(2, min(self.settings.worker_threads, 32))
        self.logger.info(
            f"Deep crawl mode={self._deep_mode}: {page_workers} page workers, "
            f"{download_workers} download workers, "
            f"max_pages={self.settings.max_pages_per_site}"
        )
        self._heartbeat_at = time.monotonic()

        with ThreadPoolExecutor(max_workers=page_workers) as page_pool, ThreadPoolExecutor(
            max_workers=download_workers
        ) as download_pool:
            pending_pages: dict = {}

            while True:
                try:
                    state = self._wait_if_paused()
                    if state == "stopped":
                        result.status = "Cancelled"
                        self.logger.warning("Crawl stopped by user")
                        break

                    if self.duplicates.visited_count >= self.settings.max_pages_per_site:
                        self.logger.info("Reached max pages per website")
                        break

                    self._maybe_heartbeat(downloader, pending_pages)
                    self._throttle_downloads()

                    # Reap finished page fetches
                    done = [fut for fut in list(pending_pages) if fut.done()]
                    for fut in done:
                        url, depth = pending_pages.pop(fut)
                        try:
                            payload = fut.result()
                        except Exception as exc:
                            self.logger.error(f"Page worker error for {url}: {exc}")
                            if not is_online(self.item.url):
                                self._enqueue(url, depth, priority=True)
                            else:
                                self._mark_visited(url, None)
                            continue
                        try:
                            self._handle_fetched_page(
                                payload, depth, site_dir, downloader, download_pool, result
                            )
                        except Exception as exc:
                            self.logger.error(f"Failed processing {url}: {exc}")
                            try:
                                self._mark_visited(url, None)
                            except Exception:
                                pass

                    # Fill page worker pool
                    while (
                        len(pending_pages) < page_workers
                        and self.duplicates.visited_count + len(pending_pages)
                        < self.settings.max_pages_per_site
                    ):
                        state = self.control_state()
                        if state != "running":
                            break
                        # Never stall page discovery because downloads are busy —
                        # journal sites need issue/article HTML crawl to find PDFs.
                        item = self._pop_page()
                        if item is None:
                            break
                        url, depth = item
                        if self.duplicates.has_visited(url):
                            self._frontier_forget(url)
                            continue
                        if not self._allowed_by_robots(url):
                            self.logger.skipped(url, "robots.txt")
                            self._mark_visited(url, 0)
                            continue
                        if is_document_url(url, self.settings.download_file_types) or is_image_url(url):
                            # Scan/download first; mark visited so HTML crawl won't re-fetch.
                            self._submit_download(
                                download_pool,
                                downloader,
                                url,
                                is_image=is_image_url(url),
                            )
                            self._mark_visited(url, 200)
                            continue
                        self._emit_progress(
                            current_page=url,
                            pages=self.duplicates.visited_count,
                            emails=len(self.duplicates.emails),
                            phones=len(self.duplicates.phones),
                        )
                        fut = page_pool.submit(self._http_fetch_page, url)
                        pending_pages[fut] = (url, depth)
                        pause = max(0, self.settings.request_pause_ms) / 1000.0
                        if pause:
                            time.sleep(pause)

                    # Do NOT stop while downloads are still running — PDF scans
                    # enqueue galley/deep HTML pages that must still be crawled.
                    if not pending_pages and not self._has_queued_pages():
                        if self._pending_download_count() > 0:
                            time.sleep(0.1)
                            continue
                        break

                    if not done and pending_pages:
                        time.sleep(0.05)
                except Exception as exc:
                    # Never let one loop error kill a multi-hour crawl.
                    self.logger.error(f"Crawl loop recovered from error: {exc}")
                    time.sleep(0.5)

            self._drain_downloads()
            # Final deep passes: anything discovered while draining PDFs/docs.
            extra_passes = 0
            while (
                self._has_queued_pages()
                and self.control_state() != "stopped"
                and extra_passes < 500
                and self.duplicates.visited_count < self.settings.max_pages_per_site
            ):
                extra_passes += 1
                self.logger.info(
                    f"Deep crawl pass {extra_passes}: "
                    f"{self._queue_size()} URL(s) left after document scans"
                )
                while self._has_queued_pages() and self.control_state() != "stopped":
                    if self.duplicates.visited_count >= self.settings.max_pages_per_site:
                        break
                    item = self._pop_page()
                    if item is None:
                        break
                    url, depth = item
                    if self.duplicates.has_visited(url):
                        continue
                    if is_document_url(url, self.settings.download_file_types) or is_image_url(url):
                        self._submit_download(
                            download_pool, downloader, url, is_image=is_image_url(url)
                        )
                        self._mark_visited(url, 200)
                        continue
                    payload = self._http_fetch_page(url)
                    self._handle_fetched_page(
                        payload, depth, site_dir, downloader, download_pool, result
                    )
                self._drain_downloads()
                if not self._has_queued_pages():
                    break

        # Cap Playwright fallback so it cannot stall a site for many hours.
        if self.settings.use_playwright_fallback and self._playwright_queue:
            if self.control_state() != "stopped":
                max_pw = max(0, self.settings.max_playwright_fallback)
                overflow = len(self._playwright_queue) - max_pw
                if overflow > 0:
                    self.logger.warning(
                        f"Playwright fallback capped at {max_pw}; "
                        f"ingesting {overflow} thin/failed page(s) from last HTTP content"
                    )
                    for _ in range(overflow):
                        if not self._playwright_queue:
                            break
                        url, depth = self._playwright_queue.pop()
                        payload = self._http_fetch_page(url)
                        if payload.get("html"):
                            try:
                                self._ingest_html(
                                    html=payload["html"],
                                    url=url,
                                    final_url=payload.get("final_url") or url,
                                    status_code=payload.get("status"),
                                    depth=depth,
                                    site_dir=site_dir,
                                    downloader=downloader,
                                    download_pool=None,
                                )
                            except Exception as exc:
                                self.logger.error(f"Overflow ingest failed {url}: {exc}")
                                self._mark_visited(url, None)
                        else:
                            self._mark_visited(url, None)
                if self._playwright_queue:
                    self.logger.info(
                        f"Playwright fallback for {len(self._playwright_queue)} page(s)"
                    )
                    self._run_playwright_fallback(site_dir, downloader, result)

    def _handle_fetched_page(
        self,
        payload: dict,
        depth: int,
        site_dir: Path,
        downloader: FileDownloader,
        download_pool: ThreadPoolExecutor,
        result: SiteResult,
    ) -> None:
        url = payload["url"]
        html = payload.get("html") or ""
        status = payload.get("status")
        final_url = payload.get("final_url") or url
        error = payload.get("error")

        if payload.get("binary"):
            # Scan PDF/doc bytes for contacts; mark visited after queueing scan.
            target = final_url or url
            self._submit_download(
                download_pool,
                downloader,
                target,
                is_image=("image/" in str(error)),
            )
            self._mark_visited(url, status or 200)
            if normalize_url(target) != normalize_url(url):
                self._mark_visited(target, status or 200)
            return

        if error and not html:
            self._consecutive_network_errors += 1
            # Only pause for offline after several connectivity failures in a row.
            # Single broken URLs must not trigger slow network probes.
            if (
                self._consecutive_network_errors >= 3
                and is_connectivity_error(error)
                and not is_online(self.item.url, timeout=1.0)
            ):
                self.logger.warning(
                    f"Internet disconnected while fetching {url}. Waiting to resume…"
                )
                try:
                    self._frontier.flush()
                except Exception:
                    pass
                if self._wait_until_online():
                    self._enqueue(url, depth, priority=True)
                    self.logger.info(f"Back online — requeued {url}")
                else:
                    self._enqueue(url, depth, priority=True)
                    result.status = "Cancelled"
                    result.error = "Interrupted while offline (progress saved for Resume)"
                return
            # Broken / unreachable URL — skip and move forward immediately.
            self.logger.warning(f"Broken URL skipped, continuing: {url} ({error})")
            self._mark_visited(url, None)
            return

        if status and status >= 400:
            # Broken page (404/403/etc.) — ignore and move forward.
            self.logger.warning(f"HTTP {status} skipped, continuing: {url}")
            self._mark_visited(url, status)
            self._consecutive_network_errors = 0
            return

        self._consecutive_network_errors = 0

        # Always ingest first so deep links (e.g. /article/view/101/113) are never lost
        # while waiting on Playwright. Playwright may re-fetch later for richer HTML.
        if _looks_thin(html) and self.settings.use_playwright_fallback:
            if len(self._playwright_queue) < max(0, self.settings.max_playwright_fallback):
                self._playwright_queue.append((url, depth))
                self.logger.info(
                    f"Thin page queued for Playwright after link ingest: {url}"
                )
            else:
                self.logger.info(f"Thin page ingested without Playwright (cap reached): {url}")

        # Always ingest available HTML (never skip content we already fetched)
        self._ingest_html(
            html=html,
            url=url,
            final_url=final_url,
            status_code=status,
            depth=depth,
            site_dir=site_dir,
            downloader=downloader,
            download_pool=download_pool,
        )

    def _ingest_html(
        self,
        html: str,
        url: str,
        final_url: str,
        status_code: int | None,
        depth: int,
        site_dir: Path,
        downloader: FileDownloader,
        download_pool: ThreadPoolExecutor | None,
    ) -> None:
        self._mark_visited(normalize_url(final_url), status_code)
        if normalize_url(final_url) != normalize_url(url):
            self._mark_visited(url, status_code)
        self.logger.page_visited(final_url, status_code)

        if self.settings.contact_scan_only:
            # Light mode: do not mirror HTML to disk; still record the visited URL.
            self._append_pages_index(final_url, None, site_dir)
        else:
            try:
                html_path = html_mirror_path(site_dir, final_url)
                html_path.write_text(html, encoding="utf-8", errors="ignore")
                self._append_pages_index(final_url, html_path, site_dir)
            except Exception as exc:
                self.logger.warning(f"Could not save HTML for {final_url}: {exc}")

        try:
            parsed = self.parser.parse(
                html,
                final_url,
                self.item.url,
                allowed_doc_types=self.settings.download_file_types,
                phone_region=self._phone_region,
            )
        except Exception as exc:
            self.logger.error(f"HTML parse failed for {final_url}: {exc}")
            return

        for email in parsed.emails:
            self.duplicates.add_email(email)
        for phone in parsed.phones:
            self.duplicates.add_phone(phone)
        if parsed.emails or parsed.phones:
            self.logger.info(
                f"Contacts on {final_url}: emails={len(parsed.emails)} phones={len(parsed.phones)}"
            )
        self._flush_contacts()

        # Deep mode: unlimited practical depth so every nested page/PDF is reached.
        max_depth = (
            1_000_000
            if self._deep_mode
            else self.settings.crawl_depth
        )
        if depth < max_depth:
            links = sorted(
                parsed.internal_links,
                key=lambda u: _url_priority_rank(u),
            )
            for link in links:
                if _should_skip_crawl_url(link):
                    continue
                if same_site(link, self.item.url):
                    # Ranked heap crawls galleys/PDFs before chrome links.
                    self._enqueue(link, depth + 1, priority=_is_priority_url(link))

        # From an article abstract, immediately schedule PDF + matching galley HTML.
        self._enqueue_journal_children(final_url, parsed.document_links, parsed.internal_links)

        # Explicit OJS PDF harvest: every PDF button (/article/view/id/galley) also
        # opens the real file at /article/download/id/galley and scans it for emails.
        self._harvest_and_schedule_pdfs(
            page_url=final_url,
            html=html,
            document_links=parsed.document_links,
            internal_links=parsed.internal_links,
            depth=depth,
            downloader=downloader,
            download_pool=download_pool,
        )

        if download_pool is not None and not self.settings.contact_scan_only:
            images = parsed.image_links
            if not (
                self.settings.download_all_images or self.settings.download_complete_site
            ):
                images = images[:40]
            for img_url in images:
                self._submit_download(download_pool, downloader, img_url, is_image=True)

        self._processed_since_gc += 1
        if self._processed_since_gc >= 200:
            self._processed_since_gc = 0
            gc.collect()

        self._emit_progress(
            pages=self.duplicates.visited_count,
            documents=downloader.stats["documents"],
            emails=len(self.duplicates.emails),
            phones=len(self.duplicates.phones),
            current_page=final_url,
        )

    def _http_fetch_page(self, url: str) -> dict:
        headers = {"User-Agent": self.settings.user_agent, "Accept": "text/html,*/*"}
        timeout = httpx.Timeout(self.settings.download_timeout)
        last_error = None
        for attempt in range(1, max(1, self.settings.retry_attempts) + 1):
            try:
                with httpx.Client(
                    headers=headers,
                    timeout=timeout,
                    follow_redirects=self.settings.follow_redirects,
                    verify=False,
                    http2=False,
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                ) as client:
                    response = client.get(url)
                    if response.status_code in {429, 503}:
                        wait = min(2.0 * attempt, 15.0)
                        self.logger.warning(
                            f"HTTP {response.status_code} for {url}; backing off {wait:.1f}s"
                        )
                        time.sleep(wait)
                        continue
                    content_type = response.headers.get("content-type", "").lower()
                    if any(
                        x in content_type
                        for x in (
                            "application/pdf",
                            "application/msword",
                            "application/vnd.",
                            "application/zip",
                            "image/",
                        )
                    ):
                        return {
                            "url": url,
                            "html": "",
                            "status": response.status_code,
                            "final_url": str(response.url),
                            "error": f"binary-content:{content_type}",
                            "binary": True,
                        }
                    text = response.text or ""
                    return {
                        "url": url,
                        "html": text,
                        "status": response.status_code,
                        "final_url": str(response.url),
                        "error": None,
                    }
            except Exception as exc:
                last_error = exc
                time.sleep(min(0.35 * attempt, 2.0))
        return {
            "url": url,
            "html": "",
            "status": None,
            "final_url": url,
            "error": str(last_error),
        }

    def _submit_download(
        self,
        pool: ThreadPoolExecutor,
        downloader: FileDownloader,
        url: str,
        is_image: bool,
    ) -> None:
        if not url or '"' in url or "'" in url or " " in url.strip():
            return
        if not self.duplicates.should_download(url):
            return
        # Backpressure: avoid unbounded download future growth on large sites
        while self._pending_download_count() >= self.settings.max_download_queue:
            if self.control_state() == "stopped":
                return
            time.sleep(0.05)
        self._emit_progress(current_download=url)
        fut = pool.submit(downloader.download, url, is_image)
        with self._lock:
            self._download_futures.add(fut)

        def _done(f) -> None:
            with self._lock:
                self._download_futures.discard(f)
            try:
                f.result()
            except Exception as exc:
                self.logger.warning(f"Download error: {exc}")

        fut.add_done_callback(_done)

    def _pending_download_count(self) -> int:
        with self._lock:
            return sum(1 for f in self._download_futures if not f.done())

    def _throttle_downloads(self) -> None:
        # Keep memory/socket usage bounded during multi-hour runs.
        while self._pending_download_count() > self.settings.max_download_queue:
            if self.control_state() == "stopped":
                return
            time.sleep(0.1)

    def _maybe_heartbeat(self, downloader: FileDownloader, pending_pages: dict) -> None:
        now = time.monotonic()
        if now - self._heartbeat_at < 15:
            return
        self._heartbeat_at = now
        with self._lock:
            qsize = len(self._page_heap)
            pw = len(self._playwright_queue)
        self.logger.info(
            "Heartbeat: "
            f"visited={self.duplicates.visited_count} queued={qsize} "
            f"pending_pages={len(pending_pages)} downloads={self._pending_download_count()} "
            f"emails={len(self.duplicates.emails)} phones={len(self.duplicates.phones)} "
            f"docs={downloader.stats['documents']} pw_fallback={pw}"
        )
        try:
            self._frontier.flush()
        except Exception:
            pass
        self._flush_contacts(force=True)

    def _append_pages_index(
        self, final_url: str, html_path: Path | None, site_dir: Path
    ) -> None:
        if html_path is None:
            rel = "(scanned, not saved)"
        else:
            try:
                rel = str(html_path.relative_to(site_dir))
            except Exception:
                rel = str(html_path)
        line = f"{final_url}\t{rel}"
        self._pages_index.append(line)
        # Flush incrementally so a crash still leaves an index.
        if len(self._pages_index) >= 25:
            self._write_pages_index(site_dir, append_only=True)

    def _drain_downloads(self) -> None:
        waited = 0.0
        while True:
            with self._lock:
                pending = [f for f in self._download_futures if not f.done()]
            if not pending:
                break
            time.sleep(0.05)
            waited += 0.05
            if waited > 600:
                self.logger.warning("Download drain timeout; continuing site finalize")
                break

    def _run_playwright_fallback(
        self,
        site_dir: Path,
        downloader: FileDownloader,
        result: SiteResult,
    ) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            self.logger.warning(f"Playwright unavailable for fallback: {exc}")
            # Mark remaining fallback URLs visited via HTTP one more time
            while self._playwright_queue:
                url, depth = self._playwright_queue.popleft()
                payload = self._http_fetch_page(url)
                if payload.get("html"):
                    self._ingest_html(
                        html=payload["html"],
                        url=url,
                        final_url=payload.get("final_url") or url,
                        status_code=payload.get("status"),
                        depth=depth,
                        site_dir=site_dir,
                        downloader=downloader,
                        download_pool=None,
                    )
                    for doc in self.parser.parse(
                        payload["html"],
                        payload.get("final_url") or url,
                        self.item.url,
                        self.settings.download_file_types,
                        self._phone_region,
                    ).document_links:
                        downloader.download(doc)
                else:
                    self._mark_visited(url, None)
            return

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=self.settings.user_agent,
                ignore_https_errors=True,
            )
            context.set_default_timeout(min(self.settings.page_timeout_ms, 20000))
            page = context.new_page()
            try:
                while self._playwright_queue:
                    if self._wait_if_paused() == "stopped":
                        result.status = "Cancelled"
                        break
                    if self.duplicates.visited_count >= self.settings.max_pages_per_site:
                        break
                    url, depth = self._playwright_queue.popleft()
                    if self.duplicates.has_visited(url):
                        self._frontier_forget(url)
                        continue
                    try:
                        response = page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=min(self.settings.page_timeout_ms, 20000),
                        )
                        try:
                            page.wait_for_load_state("networkidle", timeout=2500)
                        except Exception:
                            pass
                        html = page.content() or ""
                        final_url = page.url
                        status = response.status if response else None
                    except Exception as exc:
                        self.logger.error(f"Playwright failed for {url}: {exc}")
                        # Last resort: keep whatever HTTP can get
                        payload = self._http_fetch_page(url)
                        html = payload.get("html") or ""
                        final_url = payload.get("final_url") or url
                        status = payload.get("status")
                        if not html:
                            if not is_online(self.item.url):
                                self._enqueue(url, depth, priority=True)
                            else:
                                self.logger.warning(
                                    f"Broken URL skipped after Playwright, continuing: {url}"
                                )
                                self._mark_visited(url, None)
                            continue

                    if status and status >= 400 and not html:
                        self.logger.warning(f"HTTP {status} skipped, continuing: {url}")
                        self._mark_visited(url, status)
                        continue

                    self._ingest_html(
                        html=html,
                        url=url,
                        final_url=final_url,
                        status_code=status,
                        depth=depth,
                        site_dir=site_dir,
                        downloader=downloader,
                        download_pool=None,
                    )
                    # Sync download docs for fallback pages
                    parsed = self.parser.parse(
                        html,
                        final_url,
                        self.item.url,
                        self.settings.download_file_types,
                        self._phone_region,
                    )
                    for doc_url in parsed.document_links:
                        downloader.download(doc_url)
                    if not self.settings.contact_scan_only:
                        images = parsed.image_links
                        if (
                            self.settings.download_all_images
                            or self.settings.download_complete_site
                        ):
                            for img_url in images:
                                downloader.download(img_url, True)
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                context.close()
                browser.close()

    def _wait_if_paused(self) -> str:
        state = self.control_state()
        while state == "paused":
            time.sleep(0.2)
            state = self.control_state()
        return state

    def _pop_page(self) -> tuple[str, int] | None:
        """Pop deepest/highest-priority URL first. Frontier stays until finished."""
        with self._lock:
            if not self._page_heap:
                return None
            _rank, _seq, depth, url = heapq.heappop(self._page_heap)
            # Allow re-queue after offline / retry (visited check still applies).
            self._queued.discard(url)
            return url, depth

    def _has_queued_pages(self) -> bool:
        with self._lock:
            return bool(self._page_heap)

    def _queue_size(self) -> int:
        with self._lock:
            return len(self._page_heap)

    def _enqueue(self, url: str, depth: int, priority: bool = False) -> None:
        normalized = normalize_url(url)
        if not normalized:
            return
        if _should_skip_crawl_url(normalized):
            return
        rank = _url_priority_rank(normalized)
        # Explicit priority=True bumps at least to journal-level urgency.
        if priority and rank > 2:
            rank = min(rank, 2)
        with self._lock:
            if normalized in self._queued or self.duplicates.has_visited(normalized):
                return
            # Deep mode allows a much larger frontier so no page/PDF is dropped.
            max_queue = self.settings.max_pages_per_site * (10 if self._deep_mode else 3)
            if len(self._queued) >= max_queue:
                return
            self._queued.add(normalized)
            self._queue_seq += 1
            heapq.heappush(self._page_heap, (rank, self._queue_seq, depth, normalized))
            try:
                self._frontier.add(normalized, depth, priority=rank)
            except Exception as exc:
                self.logger.debug(f"Frontier persist failed for {normalized}: {exc}")

    def _enqueue_journal_children(
        self,
        page_url: str,
        document_links: list[str],
        internal_links: list[str],
    ) -> None:
        """Ensure /article/view/{id}/{galley} pages are queued right after abstracts."""
        path = urlparse(page_url).path
        m = re.search(r"/article/view/(\d+)/?$", path)
        if not m:
            return
        article_id = m.group(1)
        queued = 0
        for link in internal_links:
            if re.search(rf"/article/view/{article_id}/\d+", link):
                self._enqueue(link, 1, priority=True)
                queued += 1
                download = _download_from_galley_view(link)
                if download:
                    self._enqueue(download, 1, priority=True)
                    queued += 1
        for doc in document_links:
            if f"/article/download/{article_id}/" in doc:
                galley = _galley_view_from_download(doc)
                if galley:
                    self._enqueue(galley, 1, priority=True)
                    queued += 1
                self._enqueue(doc, 1, priority=True)
                queued += 1
        if queued:
            self.logger.info(
                f"Queued {queued} galley/PDF URL(s) under article/view/{article_id}"
            )

    def _harvest_and_schedule_pdfs(
        self,
        page_url: str,
        html: str,
        document_links: list[str],
        internal_links: list[str],
        depth: int,
        downloader: FileDownloader,
        download_pool: ThreadPoolExecutor | None,
    ) -> None:
        """Find every PDF button / download link on a page and scan the PDF bytes."""
        downloads: list[str] = []
        galleys: list[str] = []
        seen_dl: set[str] = set()
        seen_galley: set[str] = set()

        def _add_download(u: str) -> None:
            n = normalize_url(u)
            if not n or n in seen_dl or _should_skip_crawl_url(n):
                return
            if not same_site(n, self.item.url):
                return
            if not (looks_like_document_path(n) or "/article/download/" in n):
                # Synthesize from galley view when needed.
                synthesized = _download_from_galley_view(n)
                if synthesized:
                    _add_download(synthesized)
                    _add_galley(n)
                return
            seen_dl.add(n)
            downloads.append(n)

        def _add_galley(u: str) -> None:
            n = normalize_url(u)
            if not n or n in seen_galley or _should_skip_crawl_url(n):
                return
            if not same_site(n, self.item.url):
                return
            if not re.search(r"/article/view/\d+/\d+", n):
                return
            seen_galley.add(n)
            galleys.append(n)

        for doc in document_links:
            _add_download(doc)
            galley = _galley_view_from_download(doc)
            if galley:
                _add_galley(galley)
        for link in internal_links:
            if re.search(r"/article/view/\d+/\d+", link or ""):
                _add_galley(link)
                download = _download_from_galley_view(link)
                if download:
                    _add_download(download)
            if looks_like_document_path(link or ""):
                _add_download(link)

        # Belt-and-suspenders: regex over raw HTML for any missed PDF targets.
        for match in re.finditer(
            r"""(?:https?:)?//[^"'\\\s<>]+/article/download/\d+/\d+(?:/\d+)?""",
            html or "",
            re.I,
        ):
            _add_download(urljoin(page_url, match.group(0).replace("\\/", "/")))
        for match in re.finditer(
            r"""(?:https?:)?//[^"'\\\s<>]+/article/view/\d+/\d+/?""",
            html or "",
            re.I,
        ):
            galley = urljoin(page_url, match.group(0).replace("\\/", "/"))
            _add_galley(galley)
            download = _download_from_galley_view(galley)
            if download:
                _add_download(download)
        for match in re.finditer(
            r"""pdfUrl\s*=\s*["']([^"']+)["']""", html or "", re.I
        ):
            _add_download(urljoin(page_url, match.group(1).replace("\\/", "/")))

        for galley in galleys:
            self._enqueue(galley, depth + 1, priority=True)

        scheduled = 0
        for doc_url in downloads:
            self._enqueue(doc_url, depth + 1, priority=True)
            if download_pool is not None:
                self._submit_download(download_pool, downloader, doc_url, is_image=False)
                scheduled += 1
            else:
                scheduled += 1

        if downloads or galleys:
            self.logger.info(
                f"PDF harvest on {page_url}: "
                f"{len(downloads)} PDF download(s), {len(galleys)} galley page(s) "
                f"(scheduled={scheduled})"
            )

    def _mark_visited(self, url: str, status_code: int | None = None) -> None:
        self.duplicates.mark_visited(url, status_code)
        self._frontier_forget(url)

    def _frontier_forget(self, url: str) -> None:
        try:
            self._frontier.remove(url)
        except Exception:
            pass

    def _restore_frontier_from_db(self) -> int:
        """Reload unfinished URLs after power loss / reboot / crash."""
        rows = self._frontier.load_all()
        if not rows:
            return 0
        restored = 0
        stale = 0
        for url, depth, _stored_priority in rows:
            normalized = normalize_url(url)
            if not normalized:
                continue
            if self.duplicates.has_visited(normalized):
                self._frontier_forget(normalized)
                stale += 1
                continue
            with self._lock:
                if normalized in self._queued:
                    continue
                self._queued.add(normalized)
                # Always rank from the URL. Older frontiers stored bool 0/1 which
                # must not be treated as the new numeric deep-priority scale.
                rank = _url_priority_rank(normalized)
                self._queue_seq += 1
                heapq.heappush(
                    self._page_heap,
                    (rank, self._queue_seq, int(depth), normalized),
                )
                restored += 1
        if stale:
            self.logger.info(f"Cleared {stale} already-visited URL(s) from saved frontier")
        return restored

    def _wait_until_online(self) -> bool:
        """Block while offline. Returns False if the user stops the crawl."""
        if is_online(self.item.url):
            return True
        self.logger.warning(
            f"Network offline — progress is saved; waiting to resume {self.item.url}"
        )
        waited = 0
        while not is_online(self.item.url):
            state = self.control_state()
            if state == "stopped":
                self.logger.warning("Stopped while offline — click Resume when back online")
                return False
            while self.control_state() == "paused":
                time.sleep(0.2)
                if self.control_state() == "stopped":
                    return False
            time.sleep(5)
            waited += 5
            if waited % 60 == 0:
                self.logger.info(
                    f"Still offline after {waited}s — will continue automatically when internet returns"
                )
        self.logger.info("Network back online — continuing from saved frontier")
        self._consecutive_network_errors = 0
        return True

    def _seed_contact_paths(self, root: str) -> None:
        parsed = urlparse(root)
        base = f"{parsed.scheme}://{parsed.netloc}"
        for path in SEED_PATHS:
            self._enqueue(urljoin(base, path), 1, priority=True)

    def _seed_journal_paths(self, root: str) -> None:
        """Seed Open Journal Systems archive/index pages from the journal path."""
        parsed = urlparse(root)
        base = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path.rstrip("/")
        candidates = [
            f"{path}/issue/archive",
            f"{path}/issue/current",
            f"{path}/gateway/plugin/WebFeedGatewayPlugin/atom",
        ]
        # Also try parent journal path: /index.php/hi from /index.php/hi/...
        parts = [p for p in path.split("/") if p]
        if "index.php" in parts:
            idx = parts.index("index.php")
            if idx + 1 < len(parts):
                journal = "/" + "/".join(parts[: idx + 2])
                candidates.extend(
                    [
                        f"{journal}/issue/archive",
                        f"{journal}/issue/current",
                    ]
                )
                # Paginate archive deeply (OJS uses /issue/archive/2, /3, ...)
                for page_no in range(1, 201):
                    if page_no == 1:
                        candidates.append(f"{journal}/issue/archive")
                    else:
                        candidates.append(f"{journal}/issue/archive/{page_no}")
                    candidates.append(f"{journal}/issue/archive?issuesPage={page_no}")
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for rel in candidates:
            if rel not in seen:
                seen.add(rel)
                unique.append(rel)
        for rel in unique:
            self._enqueue(urljoin(base, rel), 1, priority=True)
        self.logger.info(f"Seeded {len(unique)} journal archive/index URL(s) for deep crawl")

    def _seed_oai_records(self, root: str) -> None:
        """Pull every article identifier from OAI-PMH (critical for OJS journals)."""
        parsed = urlparse(root)
        base = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path.rstrip("/")
        oai_candidates = [
            urljoin(base, f"{path}/oai"),
            urljoin(base, "/oai"),
            urljoin(base, "/index.php/hi/oai"),
            urljoin(base, "/index.php/index/oai"),
        ]
        # Derive /index.php/<journal>/oai from root.
        parts = [p for p in path.split("/") if p]
        if "index.php" in parts:
            idx = parts.index("index.php")
            if idx + 1 < len(parts):
                journal = "/" + "/".join(parts[: idx + 2])
                oai_candidates.insert(0, urljoin(base, f"{journal}/oai"))

        seen_oai: set[str] = set()
        total_articles = 0
        for oai_base in oai_candidates:
            if oai_base in seen_oai:
                continue
            seen_oai.add(oai_base)
            token: str | None = None
            pages = 0
            while pages < 200:
                pages += 1
                if token:
                    oai_url = f"{oai_base}?verb=ListIdentifiers&resumptionToken={token}"
                else:
                    oai_url = f"{oai_base}?verb=ListIdentifiers&metadataPrefix=oai_dc"
                payload = self._http_fetch_page(oai_url)
                xml = payload.get("html") or ""
                if not xml or "<identifier>" not in xml:
                    break
                ids = re.findall(r"<identifier>([^<]+)</identifier>", xml)
                if not ids:
                    break
                for ident in ids:
                    # oai:...:article/77 → article view + common download guess via crawl
                    m = re.search(r"(article)/(\d+)$", ident)
                    if not m:
                        continue
                    article_id = m.group(2)
                    # Build article view under the same journal prefix as OAI.
                    journal_prefix = oai_base.rsplit("/oai", 1)[0]
                    view_url = f"{journal_prefix}/article/view/{article_id}"
                    self._enqueue(view_url, 1, priority=True)
                    total_articles += 1
                token_match = re.search(
                    r"<resumptionToken[^>]*>([^<]+)</resumptionToken>", xml
                )
                token = token_match.group(1).strip() if token_match else None
                if not token:
                    break
            if total_articles:
                break

        if total_articles:
            self.logger.info(
                f"OAI-PMH seeded {total_articles} article page(s) "
                f"(PDF links resolved via citation_pdf_url on each article)"
            )
        else:
            self.logger.info("OAI-PMH: no article identifiers found (non-OJS site or disabled)")

    def _load_sitemaps(self, root: str) -> None:
        parsed = urlparse(root)
        base = f"{parsed.scheme}://{parsed.netloc}"
        candidates = [
            urljoin(base, "/sitemap.xml"),
            urljoin(base, "/wp-sitemap.xml"),
            urljoin(base, "/sitemap_index.xml"),
        ]
        try:
            robots_text = self._http_fetch_page(urljoin(base, "/robots.txt")).get("html") or ""
            for line in robots_text.splitlines():
                if line.lower().startswith("sitemap:"):
                    candidates.append(line.split(":", 1)[1].strip())
        except Exception:
            pass

        # Unique preserve order
        seen: set[str] = set()
        unique = []
        for sm in candidates:
            if sm and sm not in seen:
                seen.add(sm)
                unique.append(sm)

        child_maps: list[str] = []
        with ThreadPoolExecutor(max_workers=min(12, max(2, len(unique) or 2))) as pool:
            futures = {pool.submit(self._parse_sitemap_locs, sm): sm for sm in unique}
            for fut in as_completed(futures):
                sm = futures[fut]
                try:
                    page_locs, nested = fut.result()
                except Exception as exc:
                    self.logger.warning(f"Sitemap error {sm}: {exc}")
                    continue
                added = 0
                for loc in page_locs:
                    if not same_site(loc, self.item.url):
                        continue
                    self._enqueue(loc, 1, priority=_is_priority_url(loc))
                    added += 1
                if added:
                    self.logger.info(f"Queued {added} URLs from sitemap {sm}")
                for nested_url in nested:
                    if nested_url not in seen:
                        seen.add(nested_url)
                        child_maps.append(nested_url)

        if child_maps:
            with ThreadPoolExecutor(max_workers=min(16, max(2, len(child_maps)))) as pool:
                futures = {
                    pool.submit(self._parse_sitemap_locs, sm): sm for sm in child_maps
                }
                for fut in as_completed(futures):
                    sm = futures[fut]
                    try:
                        page_locs, _nested = fut.result()
                    except Exception as exc:
                        self.logger.warning(f"Sitemap error {sm}: {exc}")
                        continue
                    added = 0
                    for loc in page_locs:
                        if loc.endswith(".xml"):
                            continue
                        if not same_site(loc, self.item.url):
                            continue
                        self._enqueue(loc, 1, priority=_is_priority_url(loc))
                        added += 1
                    if added:
                        self.logger.info(f"Queued {added} URLs from sitemap {sm}")

    def _parse_sitemap_locs(self, sitemap_url: str) -> tuple[list[str], list[str]]:
        payload = self._http_fetch_page(sitemap_url)
        xml_text = payload.get("html") or ""
        status = payload.get("status")
        if not xml_text or (status and status >= 400):
            return [], []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            self.logger.warning(f"Could not parse sitemap: {sitemap_url}")
            return [], []

        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [el.text.strip() for el in root.findall(".//sm:loc", ns) if el.text]
        if not locs:
            locs = [el.text.strip() for el in root.findall(".//{*}loc") if el.text]

        pages: list[str] = []
        nested: list[str] = []
        for loc in locs:
            if loc.endswith(".xml") and "sitemap" in loc.lower():
                nested.append(loc)
            else:
                pages.append(loc)
        return pages, nested

    def _rescan_all_downloaded_files(self, site_dir: Path) -> None:
        before_e, before_p = len(self.duplicates.emails), len(self.duplicates.phones)
        patterns = (
            "HTML/**/*.html",
            "HTML/**/*.htm",
            "PDF/**/*",
            "Word/**/*",
            "Excel/**/*",
            "PowerPoint/**/*",
            "Reports/**/*",
        )
        scanned = 0
        for pattern in patterns:
            for path in site_dir.glob(pattern):
                if not path.is_file():
                    continue
                if path.name in {"emails.txt", "phone_numbers.txt", "pages_index.txt"}:
                    continue
                scanned += 1
                for email in extract_emails_from_file(path):
                    self.duplicates.add_email(email)
                for phone in extract_phones_from_file(
                    path, default_region=self._phone_region
                ):
                    self.duplicates.add_phone(phone)
        gained_e = len(self.duplicates.emails) - before_e
        gained_p = len(self.duplicates.phones) - before_p
        self.logger.info(
            f"Full download rescan ({scanned} files): +{gained_e} emails, +{gained_p} phones"
        )

    def _write_pages_index(self, site_dir: Path, append_only: bool = False) -> None:
        index_path = site_dir / "Reports" / "pages_index.txt"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        if append_only and self._pages_index:
            chunk = "\n".join(self._pages_index) + "\n"
            if not index_path.exists():
                index_path.write_text("URL\tSaved As\n" + chunk, encoding="utf-8")
            else:
                with open(index_path, "a", encoding="utf-8") as fh:
                    fh.write(chunk)
            self._pages_index.clear()
            return
        lines = ["URL\tSaved As", *self._pages_index]
        index_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        self._pages_index.clear()

    def _flush_contacts(self, force: bool = False) -> None:
        self._flush_counter += 1
        if not force and self._flush_counter % 10 != 0:
            return
        if not self._site_dir:
            return
        emails = sorted(self.duplicates.emails)
        phones = sorted(self.duplicates.phones)
        email_body = (
            f"# Emails extracted from {self.item.url}\n"
            f"# Total: {len(emails)}\n"
            + ("\n".join(emails) + ("\n" if emails else ""))
        )
        phone_body = (
            f"# Phone numbers extracted from {self.item.url}\n"
            f"# Total: {len(phones)}\n"
            + ("\n".join(phones) + ("\n" if phones else ""))
        )
        (self._site_dir / "emails.txt").write_text(email_body, encoding="utf-8")
        (self._site_dir / "phone_numbers.txt").write_text(phone_body, encoding="utf-8")
        (self._site_dir / "Reports" / "emails.txt").write_text(email_body, encoding="utf-8")
        (self._site_dir / "Reports" / "phone_numbers.txt").write_text(
            phone_body, encoding="utf-8"
        )

    def _load_robots(self, root: str) -> None:
        if self.settings.ignore_robots_txt:
            self._robots = None
            return
        parsed = urlparse(root)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        try:
            rp.set_url(robots_url)
            rp.read()
            self._robots = rp
            self.logger.info(f"Loaded robots.txt from {robots_url}")
        except Exception as exc:
            self.logger.warning(f"Could not read robots.txt: {exc}")
            self._robots = None

    def _allowed_by_robots(self, url: str) -> bool:
        if self.settings.ignore_robots_txt or self._robots is None:
            return True
        try:
            return self._robots.can_fetch(self.settings.user_agent, url)
        except Exception:
            return True

    def _emit_progress(self, **kwargs) -> None:
        if self.on_progress:
            self.on_progress(kwargs)
