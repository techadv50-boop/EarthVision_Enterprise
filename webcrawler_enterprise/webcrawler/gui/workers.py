"""Background worker bridge for the crawl engine."""

from __future__ import annotations

from webcrawler.qtcompat import QObject, Signal

from webcrawler.engine.orchestrator import CrawlEngine, ProgressState
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

    def _on_progress(self, state: ProgressState) -> None:
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

    def pause(self) -> None:
        self.engine.pause()

    def resume(self) -> None:
        self.engine.resume()

    def stop(self) -> None:
        self.engine.stop()

    def skip_site(self) -> None:
        self.engine.skip_site()

    def is_busy(self) -> bool:
        return self.engine.is_busy()
