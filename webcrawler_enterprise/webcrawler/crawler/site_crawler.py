"""Per-website Playwright crawler."""

from __future__ import annotations

import hashlib
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from webcrawler.db.duplicates import DuplicateManager
from webcrawler.downloader.file_downloader import FileDownloader
from webcrawler.logger.crawl_logger import CrawlLogger
from webcrawler.parser.html_parser import HtmlParser
from webcrawler.queue.manager import QueueItem
from webcrawler.settings.manager import AppSettings
from webcrawler.utils.folders import ensure_site_structure, site_folder
from webcrawler.utils.url import normalize_url, same_site


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
ControlFlag = Callable[[], str]  # returns running|paused|stopped


class SiteCrawler:
    """Crawl a single website until all reachable pages are processed."""

    def __init__(
        self,
        item: QueueItem,
        settings: AppSettings,
        duplicates: DuplicateManager,
        logger: CrawlLogger,
        on_progress: ProgressCallback | None = None,
        control_state: ControlFlag | None = None,
    ) -> None:
        self.item = item
        self.settings = settings
        self.duplicates = duplicates
        self.logger = logger
        self.on_progress = on_progress
        self.control_state = control_state or (lambda: "running")
        self.parser = HtmlParser()
        self._page_queue: deque[tuple[str, int]] = deque()
        self._queued: set[str] = set()
        self._lock = threading.Lock()
        self._robots: RobotFileParser | None = None

    def crawl(self) -> SiteResult:
        start = datetime.now(timezone.utc)
        site_dir = ensure_site_structure(site_folder(self.item.output_root, self.item.url))
        self.logger.set_path(site_dir / "Logs" / "crawl_log.txt")
        self.logger.info(f"Starting crawl of {self.item.url}")

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
        )

        def _on_download(url: str, path: str) -> None:
            self._emit_progress(
                current_download=url,
                documents=downloader.stats["documents"],
            )

        downloader.on_download = _on_download

        root = normalize_url(self.item.url)
        self._enqueue(root, 0)
        self._load_robots(root)

        try:
            self._run_playwright(site_dir, downloader, result)
            result.status = "Completed"
        except Exception as exc:
            result.status = "Failed"
            result.error = str(exc)
            self.logger.error(f"Site crawl failed: {exc}")

        # Persist contact files
        emails = sorted(self.duplicates.emails)
        phones = sorted(self.duplicates.phones)
        (site_dir / "emails.txt").write_text("\n".join(emails) + ("\n" if emails else ""), encoding="utf-8")
        (site_dir / "phone_numbers.txt").write_text(
            "\n".join(phones) + ("\n" if phones else ""), encoding="utf-8"
        )

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

        self.logger.info(
            f"Finished {self.item.url}: pages={result.pages_crawled} "
            f"docs={result.documents_downloaded} emails={result.emails} phones={result.phones} "
            f"status={result.status}"
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

    def _run_playwright(
        self,
        site_dir: Path,
        downloader: FileDownloader,
        result: SiteResult,
    ) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            ) from exc

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self.settings.user_agent)
            context.set_default_timeout(self.settings.page_timeout_ms)

            workers = max(1, self.settings.worker_threads)
            # Playwright sync API is not thread-safe across pages from one context
            # in all scenarios; use a pool of pages with a lock around navigation.
            pages = [context.new_page() for _ in range(min(workers, 4))]
            page_lock = threading.Lock()

            try:
                while True:
                    state = self.control_state()
                    if state == "stopped":
                        result.status = "Cancelled"
                        self.logger.warning("Crawl stopped by user")
                        break
                    while state == "paused":
                        time.sleep(0.25)
                        state = self.control_state()
                        if state == "stopped":
                            result.status = "Cancelled"
                            break
                    if result.status == "Cancelled":
                        break

                    batch: list[tuple[str, int]] = []
                    with self._lock:
                        while self._page_queue and len(batch) < len(pages):
                            if self.duplicates.visited_count + len(batch) >= self.settings.max_pages_per_site:
                                break
                            batch.append(self._page_queue.popleft())

                    if not batch:
                        break

                    def process_one(args: tuple[str, int], page_idx: int) -> None:
                        url, depth = args
                        self._process_page(
                            pages[page_idx],
                            page_lock,
                            url,
                            depth,
                            site_dir,
                            downloader,
                        )

                    if len(batch) == 1:
                        process_one(batch[0], 0)
                    else:
                        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                            futures = [
                                pool.submit(process_one, item, idx)
                                for idx, item in enumerate(batch)
                            ]
                            for fut in as_completed(futures):
                                try:
                                    fut.result()
                                except Exception as exc:
                                    self.logger.error(f"Worker error: {exc}")
            finally:
                for pg in pages:
                    try:
                        pg.close()
                    except Exception:
                        pass
                context.close()
                browser.close()

    def _process_page(
        self,
        page,
        page_lock: threading.Lock,
        url: str,
        depth: int,
        site_dir: Path,
        downloader: FileDownloader,
    ) -> None:
        if self.duplicates.has_visited(url):
            return
        if not self._allowed_by_robots(url):
            self.logger.skipped(url, "robots.txt")
            self.duplicates.mark_visited(url, 0)
            return

        self._emit_progress(current_page=url, pages=self.duplicates.visited_count)

        status_code = None
        html = ""
        try:
            with page_lock:
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.settings.page_timeout_ms,
                )
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                status_code = response.status if response else None
                # Execute JS already done by Playwright rendering
                html = page.content()
                final_url = page.url
        except Exception as exc:
            self.logger.error(f"Failed to open {url}: {exc}")
            self.duplicates.mark_visited(url, None)
            return

        if status_code and status_code >= 400:
            self.logger.warning(f"HTTP {status_code} for {url}")
            self.duplicates.mark_visited(url, status_code)
            return

        self.duplicates.mark_visited(normalize_url(final_url), status_code)
        if normalize_url(final_url) != normalize_url(url):
            self.duplicates.mark_visited(url, status_code)

        self.logger.page_visited(final_url, status_code)

        # Save HTML snapshot
        try:
            safe = hashlib.sha1(normalize_url(final_url).encode()).hexdigest()[:12]
            html_path = site_dir / "HTML" / f"{safe}.html"
            html_path.write_text(html, encoding="utf-8")
        except Exception as exc:
            self.logger.warning(f"Could not save HTML for {final_url}: {exc}")

        parsed = self.parser.parse(
            html,
            final_url,
            self.item.url,
            allowed_doc_types=self.settings.download_file_types,
        )

        new_emails = 0
        new_phones = 0
        for email in parsed.emails:
            if self.duplicates.add_email(email):
                new_emails += 1
        for phone in parsed.phones:
            if self.duplicates.add_phone(phone):
                new_phones += 1

        if depth < self.settings.crawl_depth:
            for link in parsed.internal_links:
                if same_site(link, self.item.url):
                    self._enqueue(link, depth + 1)

        for doc_url in parsed.document_links:
            self._emit_progress(current_download=doc_url)
            downloader.download(doc_url)

        for img_url in parsed.image_links[:50]:  # cap images per page
            downloader.download(img_url, is_image=True)

        self._emit_progress(
            pages=self.duplicates.visited_count,
            documents=downloader.stats["documents"],
            emails=len(self.duplicates.emails),
            phones=len(self.duplicates.phones),
            current_page=final_url,
        )

    def _enqueue(self, url: str, depth: int) -> None:
        normalized = normalize_url(url)
        with self._lock:
            if normalized in self._queued or self.duplicates.has_visited(normalized):
                return
            if len(self._queued) >= self.settings.max_pages_per_site * 2:
                return
            self._queued.add(normalized)
            self._page_queue.append((normalized, depth))

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
