"""Crawl orchestration: sequential websites with pause/resume/stop."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from webcrawler.crawler.site_crawler import SiteCrawler, SiteResult
from webcrawler.db.database import Database
from webcrawler.db.duplicates import DuplicateManager
from webcrawler.logger.crawl_logger import CrawlLogger
from webcrawler.queue.manager import QueueManager, QueueStatus
from webcrawler.reports.generator import append_master_report, write_summary
from webcrawler.settings.manager import AppSettings
from webcrawler.utils.url import parse_url_list


@dataclass
class ProgressState:
    current_website: str = ""
    current_page: str = ""
    current_download: str = ""
    websites_completed: int = 0
    websites_remaining: int = 0
    websites_total: int = 0
    pages_crawled: int = 0
    documents_downloaded: int = 0
    emails_found: int = 0
    phone_numbers_found: int = 0
    elapsed_seconds: float = 0.0
    estimated_remaining_seconds: float | None = None
    status: str = "Idle"
    message: str = ""


ProgressHandler = Callable[[ProgressState], None]
LogHandler = Callable[[str], None]
FinishedHandler = Callable[[], None]


class CrawlEngine:
    """Process websites one at a time from the persistent queue."""

    def __init__(
        self,
        db: Database | None = None,
        settings: AppSettings | None = None,
        on_progress: ProgressHandler | None = None,
        on_log: LogHandler | None = None,
        on_finished: FinishedHandler | None = None,
    ) -> None:
        self.db = db or Database()
        self.settings = settings or AppSettings()
        self.queue = QueueManager(self.db)
        self.on_progress = on_progress
        self.on_log = on_log
        self.on_finished = on_finished

        self._thread: threading.Thread | None = None
        self._state = "idle"  # idle|running|paused|stopped
        self._state_lock = threading.Lock()
        self._progress = ProgressState()
        self._start_monotonic = 0.0
        self._site_durations: list[float] = []
        self._resume_mode = False
        # Sites the user skipped this run (still Pending for later Resume).
        self._deferred_site_ids: set[int] = set()
        self._skip_site = False

    @property
    def progress(self) -> ProgressState:
        return self._progress

    def control_state(self) -> str:
        with self._state_lock:
            if self._skip_site:
                return "skip_site"
            return self._state

    def start(self, urls_text: str, output_folder: str, settings: AppSettings | None = None) -> None:
        if self.is_busy():
            raise RuntimeError("Crawl already in progress")
        if settings is not None:
            self.settings = settings

        output = Path(output_folder)
        if not output_folder or not output.exists():
            raise ValueError("Output folder does not exist")

        urls = parse_url_list(urls_text)
        if not urls:
            raise ValueError("No valid URLs provided")

        # Start = only the URLs in the box, from scratch (do not resume old sites).
        self._resume_mode = False
        self._deferred_site_ids = set()
        self._skip_site = False
        items = self.queue.start_new_batch(urls, str(output.resolve()))

        with self._state_lock:
            self._state = "running"
        self._start_monotonic = time.monotonic()
        self._site_durations = []
        self._progress = ProgressState(
            status="Running",
            websites_total=len(items),
        )
        self._thread = threading.Thread(target=self._run_loop, name="CrawlEngine", daemon=True)
        self._thread.start()

    def resume_queue(self, settings: AppSettings | None = None) -> None:
        """Resume unfinished Pending items after crash / pause."""
        if self.is_busy():
            raise RuntimeError("Crawl already in progress")
        if settings is not None:
            self.settings = settings
        self._resume_mode = True
        self._deferred_site_ids = set()
        self._skip_site = False
        self.queue.prepare_resume()
        counts = self.queue.counts()
        if counts.get(QueueStatus.PENDING.value, 0) == 0:
            raise ValueError("No unfinished websites to resume")
        with self._state_lock:
            self._state = "running"
        self._start_monotonic = time.monotonic()
        self._progress = ProgressState(
            status="Running",
            websites_total=counts.get(QueueStatus.PENDING.value, 0),
        )
        self._thread = threading.Thread(target=self._run_loop, name="CrawlEngine", daemon=True)
        self._thread.start()

    def pause(self) -> None:
        with self._state_lock:
            if self._state == "running":
                self._state = "paused"
                self._progress.status = "Paused"
                self._emit()

    def resume(self) -> None:
        with self._state_lock:
            if self._state == "paused":
                self._state = "running"
                self._progress.status = "Running"
                self._emit()

    def stop(self) -> None:
        with self._state_lock:
            self._skip_site = False
            self._state = "stopped"
            self._progress.status = "Stopping"
            self._emit()

    def skip_site(self) -> None:
        """Abort the current website only; keep progress and continue the queue."""
        with self._state_lock:
            if self._state not in {"running", "paused"}:
                return
            self._skip_site = True
            # Unpause so the crawler can exit the current site promptly.
            if self._state == "paused":
                self._state = "running"
            self._progress.status = "Skipping site"
            self._progress.message = "Saving progress, then jumping to the next website…"
            self._emit()

    def is_busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _clear_skip_flag(self) -> bool:
        with self._state_lock:
            was = self._skip_site
            self._skip_site = False
            return was

    def _pending_and_running_count(self) -> int:
        counts = self.queue.counts()
        return counts.get(QueueStatus.PENDING.value, 0) + counts.get(QueueStatus.RUNNING.value, 0)

    def _run_loop(self) -> None:
        logger = CrawlLogger(on_message=self.on_log)
        completed = 0
        try:
            while True:
                try:
                    if self.control_state() == "stopped":
                        self.queue.cancel_remaining()
                        break
                    while self.control_state() == "paused":
                        time.sleep(0.2)
                        if self.control_state() == "stopped":
                            self.queue.cancel_remaining()
                            break
                        if self.control_state() == "skip_site":
                            break
                    if self.control_state() == "stopped":
                        break

                    item = self.queue.next_pending(exclude_ids=self._deferred_site_ids)
                    if item is None:
                        break

                    remaining = self._pending_and_running_count()
                    self._progress.current_website = item.url
                    self._progress.websites_remaining = max(remaining - 1, 0)
                    self._progress.websites_completed = completed
                    self._progress.status = "Running"
                    self._emit()

                    self.queue.mark_running(item.id)
                    duplicates = DuplicateManager(self.db, item.id)
                    site_start = time.monotonic()

                    def site_progress(data: dict) -> None:
                        for key, value in data.items():
                            if key == "current_page":
                                self._progress.current_page = value
                            elif key == "current_download":
                                self._progress.current_download = value
                            elif key == "pages":
                                self._progress.pages_crawled = value
                            elif key == "documents":
                                self._progress.documents_downloaded = value
                            elif key == "emails":
                                self._progress.emails_found = value
                            elif key == "phones":
                                self._progress.phone_numbers_found = value
                        self._progress.elapsed_seconds = time.monotonic() - self._start_monotonic
                        self._update_eta(completed)
                        self._emit()

                    crawler = SiteCrawler(
                        item=item,
                        settings=self.settings,
                        duplicates=duplicates,
                        logger=logger,
                        on_progress=site_progress,
                        control_state=self.control_state,
                        resume_mode=self._resume_mode,
                    )

                    try:
                        result = crawler.crawl()
                    except Exception as exc:
                        result = SiteResult(
                            website=item.url,
                            domain=item.domain,
                            status="Failed",
                            error=str(exc),
                            start_time=datetime.now(timezone.utc).isoformat(),
                            end_time=datetime.now(timezone.utc).isoformat(),
                            site_dir=Path(item.output_root) / item.domain,
                        )
                        logger.error(f"Unhandled error for {item.url}: {exc}")

                    try:
                        write_summary(result)
                    except Exception as exc:
                        logger.error(f"Summary write failed for {item.url}: {exc}")
                    try:
                        append_master_report(item.output_root, result)
                    except Exception as exc:
                        logger.error(f"Master report update failed for {item.url}: {exc}")

                    try:
                        if result.status == "Completed":
                            self._clear_skip_flag()
                            self.queue.mark_completed(item.id)
                        elif result.status == "Cancelled":
                            skipped = self._clear_skip_flag()
                            if skipped or "skip" in (result.error or "").lower():
                                # Keep progress; do not crawl this site again until Resume.
                                self._deferred_site_ids.add(item.id)
                                self.queue.mark_pending(
                                    item.id,
                                    result.error
                                    or "Skipped to next site — click Resume later to continue",
                                )
                                logger.warning(
                                    f"Skipped {item.url} — progress saved; jumping to next site"
                                )
                                self._progress.message = (
                                    f"Skipped {item.domain}; moving to next website"
                                )
                                self._progress.status = "Running"
                                self._emit()
                                continue
                            # Full Stop — keep Pending so Resume can continue mid-site.
                            self.queue.mark_pending(
                                item.id,
                                result.error or "Interrupted — click Resume to continue",
                            )
                            break
                        else:
                            self._clear_skip_flag()
                            # Do not lose mid-site progress; Resume retries this site later.
                            self.queue.mark_failed(
                                item.id,
                                result.error or "Failed — click Resume to continue from saved progress",
                            )
                    except Exception as exc:
                        logger.error(f"Queue status update failed for {item.url}: {exc}")

                    completed += 1
                    self._site_durations.append(time.monotonic() - site_start)
                    if len(self._site_durations) > 200:
                        self._site_durations = self._site_durations[-100:]
                    self._progress.websites_completed = completed
                    self._progress.websites_remaining = self._pending_and_running_count()
                    self._progress.emails_found = result.emails
                    self._progress.phone_numbers_found = result.phones
                    self._progress.pages_crawled = result.pages_crawled
                    self._progress.documents_downloaded = result.documents_downloaded
                    self._progress.message = f"Finished {item.domain} ({result.status})"
                    self._update_eta(completed)
                    self._emit()

                    if self.control_state() == "stopped":
                        self.queue.cancel_remaining()
                        break
                except Exception as exc:
                    # Keep processing remaining websites after unexpected errors.
                    logger.error(f"Crawl engine recovered from site-loop error: {exc}")
                    time.sleep(1.0)
                    continue
        finally:
            with self._state_lock:
                self._state = "idle"
                self._skip_site = False
            self._progress.status = "Idle"
            self._progress.current_website = ""
            self._progress.current_page = ""
            self._progress.current_download = ""
            if self._deferred_site_ids:
                self._progress.message = (
                    "Queue finished for this run. Skipped site(s) remain "
                    "available under Resume."
                )
            else:
                self._progress.message = "All queued websites processed"
            self._emit()
            if self.on_finished:
                try:
                    self.on_finished()
                except Exception:
                    pass

    def _update_eta(self, completed: int) -> None:
        remaining = self._progress.websites_remaining
        if completed > 0 and remaining > 0 and self._site_durations:
            avg = sum(self._site_durations) / len(self._site_durations)
            self._progress.estimated_remaining_seconds = avg * remaining
        else:
            self._progress.estimated_remaining_seconds = None
        self._progress.elapsed_seconds = time.monotonic() - self._start_monotonic

    def _emit(self) -> None:
        if self.on_progress:
            self.on_progress(self._progress)
