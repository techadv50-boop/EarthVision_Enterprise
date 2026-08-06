"""Live progress panel."""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel

from webcrawler.engine.orchestrator import ProgressState


def _fmt_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class ProgressPanel(QGroupBox):
    def __init__(self, parent=None) -> None:
        super().__init__("Progress", parent)
        self.labels: dict[str, QLabel] = {}
        layout = QFormLayout(self)
        fields = [
            ("status", "Status"),
            ("current_website", "Current Website"),
            ("current_page", "Current Page"),
            ("current_download", "Current Download"),
            ("websites_completed", "Websites Completed"),
            ("websites_remaining", "Websites Remaining"),
            ("pages_crawled", "Pages Crawled"),
            ("documents_downloaded", "Documents Downloaded"),
            ("emails_found", "Emails Found"),
            ("phone_numbers_found", "Phone Numbers Found"),
            ("elapsed", "Elapsed Time"),
            ("eta", "Estimated Remaining"),
        ]
        for key, title in fields:
            label = QLabel("—")
            label.setWordWrap(True)
            self.labels[key] = label
            layout.addRow(f"{title}:", label)

    def update_state(self, state: ProgressState) -> None:
        self.labels["status"].setText(state.status or "—")
        self.labels["current_website"].setText(state.current_website or "—")
        self.labels["current_page"].setText(state.current_page or "—")
        self.labels["current_download"].setText(state.current_download or "—")
        self.labels["websites_completed"].setText(str(state.websites_completed))
        self.labels["websites_remaining"].setText(str(state.websites_remaining))
        self.labels["pages_crawled"].setText(str(state.pages_crawled))
        self.labels["documents_downloaded"].setText(str(state.documents_downloaded))
        self.labels["emails_found"].setText(str(state.emails_found))
        self.labels["phone_numbers_found"].setText(str(state.phone_numbers_found))
        self.labels["elapsed"].setText(_fmt_seconds(state.elapsed_seconds))
        self.labels["eta"].setText(_fmt_seconds(state.estimated_remaining_seconds))
