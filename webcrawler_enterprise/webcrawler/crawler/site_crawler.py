"""Per-website Playwright crawler with reliable contact extraction."""

from __future__ import annotations

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
from webcrawler.downloader.file_downloader import FileDownloader
from webcrawler.extractors.email import extract_emails_from_file
from webcrawler.extractors.phone import extract_phones_from_file, region_from_url
from webcrawler.logger.crawl_logger import CrawlLogger
from webcrawler.parser.html_parser import HtmlParser
from webcrawler.queue.manager import QueueItem
from webcrawler.settings.manager import AppSettings
from webcrawler.utils.folders import ensure_site_structure, html_mirror_path, site_folder
from webcrawler.utils.url import normalize_url, same_site

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
        self._phone_region = region_from_url(item.url)
        self._site_dir: Path | None = None
        self._flush_counter = 0
        self._pages_index: list[str] = []

    def crawl(self) -> SiteResult:
        start = datetime.now(timezone.utc)
        site_dir = ensure_site_structure(site_folder(self.item.output_root, self.item.url))
        self._site_dir = site_dir
        self.logger.set_path(site_dir / "Logs" / "crawl_log.txt")
        self.logger.info(f"Starting full-site download of {self.item.url}")
        self.logger.info(f"Phone default region inferred as {self._phone_region}")

        if self.settings.fresh_site_crawl or self.settings.download_complete_site:
            self.duplicates.clear_crawl_state(clear_contacts=True)
            self.logger.info("Cleared previous crawl state for a fresh complete download")

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
            # Extract contacts from every downloaded document immediately.
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
        self._enqueue(root, 0, priority=True)
        self._seed_contact_paths(root)
        self._load_robots(root)
        self._load_sitemaps(root)

        try:
            self._run_playwright(site_dir, downloader, result)
            if result.status != "Cancelled":
                result.status = "Completed"
        except Exception as exc:
            result.status = "Failed"
            result.error = str(exc)
            self.logger.error(f"Site crawl failed: {exc}")

        # Scan every downloaded file (HTML + documents) for emails/phones
        self._rescan_all_downloaded_files(site_dir)
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

        # Playwright sync API is not thread-safe. Navigate pages sequentially.
        # Use a thread pool only for document downloads.
        download_workers = max(1, min(self.settings.worker_threads, 6))

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=self.settings.user_agent,
                ignore_https_errors=True,
            )
            context.set_default_timeout(self.settings.page_timeout_ms)
            page = context.new_page()

            try:
                with ThreadPoolExecutor(max_workers=download_workers) as pool:
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

                        if self.duplicates.visited_count >= self.settings.max_pages_per_site:
                            self.logger.info("Reached max pages per website")
                            break

                        with self._lock:
                            if not self._page_queue:
                                break
                            url, depth = self._page_queue.popleft()

                        doc_urls, image_urls = self._process_page(
                            page, url, depth, site_dir
                        )

                        futures = []
                        for doc_url in doc_urls:
                            self._emit_progress(current_download=doc_url)
                            futures.append(pool.submit(downloader.download, doc_url))
                        images_to_get = (
                            image_urls
                            if self.settings.download_all_images
                            or self.settings.download_complete_site
                            else image_urls[:40]
                        )
                        for img_url in images_to_get:
                            futures.append(
                                pool.submit(downloader.download, img_url, True)
                            )
                        for fut in as_completed(futures):
                            try:
                                fut.result()
                            except Exception as exc:
                                self.logger.warning(f"Download worker error: {exc}")
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                context.close()
                browser.close()

    def _process_page(
        self,
        page,
        url: str,
        depth: int,
        site_dir: Path,
    ) -> tuple[list[str], list[str]]:
        if self.duplicates.has_visited(url):
            return [], []
        if not self._allowed_by_robots(url):
            self.logger.skipped(url, "robots.txt")
            self.duplicates.mark_visited(url, 0)
            return [], []

        self._emit_progress(current_page=url, pages=self.duplicates.visited_count)

        status_code = None
        html = ""
        final_url = url
        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.settings.page_timeout_ms,
            )
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            # Give late JS a moment on contact-heavy pages
            if _is_priority_url(url):
                try:
                    page.wait_for_timeout(1200)
                except Exception:
                    pass
            status_code = response.status if response else None
            html = page.content() or ""
            final_url = page.url
        except Exception as exc:
            self.logger.warning(f"Playwright failed for {url}: {exc}")
            html, status_code, final_url = self._httpx_fetch(url)
            if not html:
                self.logger.error(f"Failed to open {url}: {exc}")
                self.duplicates.mark_visited(url, None)
                return [], []

        # Fallback when rendered page looks empty / blocked
        if len(html) < 500 or not re.search(r"<body", html, re.I):
            alt_html, alt_status, alt_final = self._httpx_fetch(url)
            if alt_html and len(alt_html) > len(html):
                self.logger.info(f"Using HTTP fallback content for {url}")
                html, status_code, final_url = alt_html, alt_status, alt_final

        if status_code and status_code >= 400:
            self.logger.warning(f"HTTP {status_code} for {url}")
            self.duplicates.mark_visited(url, status_code)
            return [], []

        self.duplicates.mark_visited(normalize_url(final_url), status_code)
        if normalize_url(final_url) != normalize_url(url):
            self.duplicates.mark_visited(url, status_code)

        self.logger.page_visited(final_url, status_code)

        html_path: Path | None = None
        try:
            html_path = html_mirror_path(site_dir, final_url)
            html_path.write_text(html, encoding="utf-8")
            self._pages_index.append(f"{final_url}\t{html_path.relative_to(site_dir)}")
        except Exception as exc:
            self.logger.warning(f"Could not save HTML for {final_url}: {exc}")

        parsed = self.parser.parse(
            html,
            final_url,
            self.item.url,
            allowed_doc_types=self.settings.download_file_types,
            phone_region=self._phone_region,
        )

        for email in parsed.emails:
            self.duplicates.add_email(email)
        for phone in parsed.phones:
            self.duplicates.add_phone(phone)

        if parsed.emails or parsed.phones:
            self.logger.info(
                f"Contacts on {final_url}: emails={len(parsed.emails)} phones={len(parsed.phones)}"
            )
        self._flush_contacts()

        # Complete-site mode follows every internal link until max pages is reached.
        max_depth = (
            10_000
            if self.settings.download_complete_site
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

        self._emit_progress(
            pages=self.duplicates.visited_count,
            emails=len(self.duplicates.emails),
            phones=len(self.duplicates.phones),
            current_page=final_url,
        )
        return parsed.document_links, parsed.image_links

    def _httpx_fetch(self, url: str) -> tuple[str, int | None, str]:
        try:
            with httpx.Client(
                headers={"User-Agent": self.settings.user_agent},
                timeout=self.settings.download_timeout,
                follow_redirects=self.settings.follow_redirects,
                verify=False,
            ) as client:
                response = client.get(url)
                return response.text or "", response.status_code, str(response.url)
        except Exception as exc:
            self.logger.warning(f"HTTP fallback failed for {url}: {exc}")
            return "", None, url

    def _enqueue(self, url: str, depth: int, priority: bool = False) -> None:
        normalized = normalize_url(url)
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
        # Include sitemap from robots.txt if present
        try:
            robots_text = self._httpx_fetch(urljoin(base, "/robots.txt"))[0]
            for line in robots_text.splitlines():
                if line.lower().startswith("sitemap:"):
                    candidates.append(line.split(":", 1)[1].strip())
        except Exception:
            pass

        seen_maps: set[str] = set()
        for sm_url in candidates:
            if not sm_url or sm_url in seen_maps:
                continue
            seen_maps.add(sm_url)
            self._ingest_sitemap(sm_url, depth=0)

    def _ingest_sitemap(self, sitemap_url: str, depth: int) -> None:
        if depth > 2:
            return
        xml_text, status, _ = self._httpx_fetch(sitemap_url)
        if not xml_text or (status and status >= 400):
            return
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            self.logger.warning(f"Could not parse sitemap: {sitemap_url}")
            return

        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [el.text.strip() for el in root.findall(".//sm:loc", ns) if el.text]
        if not locs:
            locs = [el.text.strip() for el in root.findall(".//{*}loc") if el.text]

        added = 0
        for loc in locs:
            if loc.endswith(".xml") and "sitemap" in loc.lower():
                self._ingest_sitemap(loc, depth + 1)
                continue
            if not same_site(loc, self.item.url):
                continue
            self._enqueue(loc, 1, priority=_is_priority_url(loc))
            added += 1
            if added >= self.settings.max_pages_per_site:
                break
        if added:
            self.logger.info(f"Queued {added} URLs from sitemap {sitemap_url}")

    def _rescan_all_downloaded_files(self, site_dir: Path) -> None:
        """Scan HTML + documents so contact text files are complete."""
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
            f"Full download rescan ({scanned} files): "
            f"+{gained_e} emails, +{gained_p} phones"
        )

    def _write_pages_index(self, site_dir: Path) -> None:
        index_path = site_dir / "Reports" / "pages_index.txt"
        lines = ["URL\tSaved As", *self._pages_index]
        index_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def _flush_contacts(self, force: bool = False) -> None:
        self._flush_counter += 1
        if not force and self._flush_counter % 3 != 0:
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

        # Primary location required by the product
        (self._site_dir / "emails.txt").write_text(email_body, encoding="utf-8")
        (self._site_dir / "phone_numbers.txt").write_text(phone_body, encoding="utf-8")
        # Copies under Reports for easy browsing
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
