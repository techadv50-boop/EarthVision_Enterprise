"""Background worker bridge for the crawl engine."""

from __future__ import annotations

from webcrawler.qtcompat import QObject, Signal

from webcrawler.engine.orchestrator import CrawlEngine, ProgressState
from webcrawler.scanner.folder_scanner import FolderScanner
from webcrawler.settings.manager import AppSettings


class CrawlWorker(QObject):
    """Owns CrawlEngine and exposes Qt signals for the UI thread."""

    progress = Signal(object)
    log_message = Signal(str)
    finished = Signal()
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.engine = CrawlEngine(
            on_progress=self._on_progress,
            on_log=self._on_log,
            on_finished=self._on_finished,
        )
        self.folder_scanner = FolderScanner(
            on_progress=self._on_folder_progress,
            on_log=self._on_log,
            on_finished=self._on_finished,
        )

    def _on_progress(self, state: ProgressState) -> None:
        self.progress.emit(state)

    def _on_folder_progress(self, data: dict) -> None:
        state = ProgressState(
            status=str(data.get("status") or "Scanning folder"),
            current_website=str(data.get("current_website") or ""),
            current_page=str(data.get("current_page") or ""),
            current_download=str(data.get("current_download") or ""),
            websites_completed=int(data.get("websites_completed") or 0),
            websites_remaining=int(data.get("websites_remaining") or 0),
            websites_total=int(data.get("websites_total") or 1),
            pages_crawled=int(data.get("pages_crawled") or 0),
            documents_downloaded=int(data.get("documents_downloaded") or 0),
            emails_found=int(data.get("emails_found") or 0),
            phone_numbers_found=int(data.get("phone_numbers_found") or 0),
            elapsed_seconds=float(data.get("elapsed_seconds") or 0.0),
            message=str(data.get("message") or ""),
        )
        self.progress.emit(state)

    def _on_log(self, message: str) -> None:
        self.log_message.emit(message)

    def _on_finished(self) -> None:
        self.finished.emit()

    def start(self, urls_text: str, output_folder: str, settings: AppSettings) -> None:
        try:
            self.engine.start(urls_text, output_folder, settings)
        except Exception as exc:
            self.error.emit(str(exc))

    def resume_queue(self, settings: AppSettings) -> None:
        try:
            self.engine.resume_queue(settings)
        except Exception as exc:
            self.error.emit(str(exc))

    def start_folder_scan(
        self,
        folder: str,
        *,
        recursive: bool = True,
        use_ocr: bool = True,
        default_region: str = "US",
    ) -> None:
        try:
            self.folder_scanner.default_region = default_region
            self.folder_scanner.start(folder, recursive=recursive, use_ocr=use_ocr)
        except Exception as exc:
            self.error.emit(str(exc))

    def pause(self) -> None:
        self.engine.pause()

    def resume(self) -> None:
        self.engine.resume()

    def stop(self) -> None:
        self.engine.stop()
        self.folder_scanner.stop()

    def skip_site(self) -> None:
        self.engine.skip_site()

    def is_busy(self) -> bool:
        return self.engine.is_busy() or self.folder_scanner.is_busy()