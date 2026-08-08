"""High-speed full-site crawler: concurrent HTTP first, Playwright fallback."""

from __future__ import annotations

import gc
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
from webcrawler.utils.url import is_document_url, is_image_url, normalize_url, same_site

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


def _is_priority_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(hint in path for hint in CONTACT_HINTS)


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
        self._page_queue: deque[tuple[str, int]] = deque()
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
        self._load_robots(root)
        self._load_sitemaps(root)
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
        page_workers = max(2, min(self.settings.page_workers, 32))
        download_workers = max(2, min(self.settings.worker_threads, 24))
        self.logger.info(
            f"Stable crawl mode: {page_workers} parallel page fetches, "
            f"{download_workers} parallel downloads"
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
                        if self._pending_download_count() >= self.settings.max_download_queue:
                            break
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
                            self._mark_visited(url, 200)
                            self._submit_download(
                                download_pool,
                                downloader,
                                url,
                                is_image=is_image_url(url),
                            )
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

                    if not pending_pages and not self._has_queued_pages():
                        break

                    if not done and pending_pages:
                        time.sleep(0.05)
                except Exception as exc:
                    # Never let one loop error kill a multi-hour crawl.
                    self.logger.error(f"Crawl loop recovered from error: {exc}")
                    time.sleep(0.5)

            self._drain_downloads()

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
            self._mark_visited(url, status or 200)
            self._submit_download(
                download_pool,
                downloader,
                final_url or url,
                is_image=("image/" in str(error)),
            )
            return

        if error and not html:
            self._consecutive_network_errors += 1
            # Only pause for offline after several connectivity failures in a row.
            # Single broken URLs must not trigger slow network probes.
            if (
                self._consecutive_network_errors >= 8
                and is_connectivity_error(error)
                and not is_online(self.item.url, timeout=1.0)
            ):
                self.logger.warning(
                    f"Internet disconnected while fetching {url}. Waiting to resume…"
                )
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

        if _looks_thin(html) and self.settings.use_playwright_fallback:
            if len(self._playwright_queue) < max(0, self.settings.max_playwright_fallback):
                self._playwright_queue.append((url, depth))
                self.logger.info(f"Thin page, queued Playwright fallback: {url}")
                return
            # Queue full: still ingest whatever HTML we have (do not skip forever)
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

        # Light mode and complete-site mode never skip pages by depth.
        max_depth = (
            10_000
            if (self.settings.download_complete_site or self.settings.contact_scan_only)
            else self.settings.crawl_depth
        )
        if depth < max_depth:
            links = sorted(
                parsed.internal_links,
                key=lambda u: (0 if _is_priority_url(u) else 1),
            )
            for link in links:
                if same_site(link, self.item.url):
                    self._enqueue(link, depth + 1, priority=_is_priority_url(link))

        if download_pool is not None:
            for doc_url in parsed.document_links:
                self._submit_download(download_pool, downloader, doc_url, is_image=False)
            if not self.settings.contact_scan_only:
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
        if now - self._heartbeat_at < 30:
            return
        self._heartbeat_at = now
        with self._lock:
            qsize = len(self._page_queue)
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
        """Pop from memory only. Frontier entry stays until the URL is finished."""
        with self._lock:
            if not self._page_queue:
                return None
            url, depth = self._page_queue.popleft()
            # Allow re-queue after offline / retry (visited check still applies).
            self._queued.discard(url)
            return url, depth

    def _has_queued_pages(self) -> bool:
        with self._lock:
            return bool(self._page_queue)

    def _enqueue(self, url: str, depth: int, priority: bool = False) -> None:
        normalized = normalize_url(url)
        if not normalized:
            return
        with self._lock:
            if normalized in self._queued or self.duplicates.has_visited(normalized):
                return
            if len(self._queued) >= self.settings.max_pages_per_site * 3:
                return
            self._queued.add(normalized)
            item = (normalized, depth)
            if priority:
                self._page_queue.appendleft(item)
            else:
                self._page_queue.append(item)
            try:
                self._frontier.add(normalized, depth, priority=priority)
            except Exception as exc:
                self.logger.debug(f"Frontier persist failed for {normalized}: {exc}")

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
        for url, depth, priority in rows:
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
                item = (normalized, int(depth))
                if priority:
                    self._page_queue.appendleft(item)
                else:
                    self._page_queue.append(item)
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
