"""WebCrawler Enterprise v1.4.2 engine, wrapped for the logged-in web app.

Preserved desktop rules from branch cursor/webcrawler-enterprise-1d95
(commit f90081f — “Resume unfinished sites from the saved page queue.”):

- Start uses only the URLs in the box, from scratch (old unfinished sites ignored).
- Sequential sites, one website at a time.
- Light mode (default): crawl all pages for emails and phones; do not save files.
- Full download mode saves HTML/docs/images.
- Broken / 404 URLs are skipped; work continues.
- Never auto-start. Resume only after the user approves.
- Resume continues unfinished sites from the last saved page; finished sites skipped.
- Next Site parks the current site (progress saved) and jumps to the next URL.
- Deep crawl / OJS galley PDF harvest / contact-page priority stay in the engine.
- Isolated per-user data (never mix queues between accounts).
"""

from __future__ import annotations

import sys
import threading
import zipfile
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.core.config import get_settings as get_app_settings

_PKG = Path(__file__).resolve().parents[3] / "webcrawler_enterprise"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from webcrawler.db.database import Database  # noqa: E402
from webcrawler.engine.orchestrator import CrawlEngine, ProgressState  # noqa: E402
from webcrawler.queue.manager import QueueManager  # noqa: E402
from webcrawler.scanner.folder_scanner import FolderScanner  # noqa: E402
from webcrawler.settings.manager import AppSettings, SettingsManager  # noqa: E402


def _user_root(user_id: int) -> Path:
    root = get_app_settings().upload_dir / "webcrawler" / str(user_id)
    root.mkdir(parents=True, exist_ok=True)
    (root / "sites").mkdir(parents=True, exist_ok=True)
    return root


def _progress_dict(state: ProgressState) -> dict[str, Any]:
    return {
        "status": state.status or "Idle",
        "current_website": state.current_website or "",
        "current_page": state.current_page or "",
        "current_download": state.current_download or "",
        "websites_completed": state.websites_completed,
        "websites_remaining": state.websites_remaining,
        "websites_total": state.websites_total,
        "pages_crawled": state.pages_crawled,
        "documents_downloaded": state.documents_downloaded,
        "emails_found": state.emails_found,
        "phone_numbers_found": state.phone_numbers_found,
        "elapsed_seconds": state.elapsed_seconds,
        "estimated_remaining_seconds": state.estimated_remaining_seconds,
        "message": state.message or "",
    }


class UserCrawlSession:
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.root = _user_root(user_id)
        self.output = self.root / "sites"
        self.db = Database(self.root / "crawler.db")
        self.settings_manager = SettingsManager(self.root / "settings.json")
        self.log: deque[str] = deque(maxlen=2000)
        self._log_lock = threading.Lock()
        self.engine = CrawlEngine(
            db=self.db,
            settings=self.settings_manager.settings,
            on_progress=lambda _state: None,
            on_log=self._append_log,
            on_finished=lambda: self._append_log("Processing finished."),
        )
        self.scanner = FolderScanner(
            on_progress=self._on_folder_progress,
            on_log=self._append_log,
            on_finished=lambda: self._append_log("Folder scan finished."),
        )

    def _append_log(self, message: str) -> None:
        text = (message or "").strip()
        if not text:
            return
        with self._log_lock:
            self.log.append(text)

    def _on_folder_progress(self, data: dict) -> None:
        msg = str(data.get("message") or data.get("status") or "")
        if msg:
            self._append_log(msg)

    def is_busy(self) -> bool:
        return self.engine.is_busy() or self.scanner.is_busy()

    def settings(self) -> AppSettings:
        return self.settings_manager.settings

    def save_settings(self, updates: dict[str, Any]) -> AppSettings:
        data = self.settings_manager.settings.to_dict()
        data.update({k: v for k, v in updates.items() if v is not None})
        settings = AppSettings.from_dict(data)
        self.settings_manager.save(settings)
        return settings

    def start(self, urls_text: str, *, light_mode: bool | None = None) -> None:
        if self.is_busy():
            raise RuntimeError("A crawl is already running.")
        settings = self.settings_manager.settings
        if light_mode is not None:
            settings = self.save_settings({"contact_scan_only": bool(light_mode)})
        self.output.mkdir(parents=True, exist_ok=True)
        self.engine.start(urls_text, str(self.output), settings)

    def resume_queue(self) -> None:
        if self.is_busy():
            raise RuntimeError("A crawl is already running.")
        self.engine.resume_queue(self.settings_manager.settings)

    def start_folder_scan(self, folder: str, *, recursive: bool, use_ocr: bool) -> None:
        if self.is_busy():
            raise RuntimeError("Stop the current job before scanning a folder.")
        self.scanner.start(folder, recursive=recursive, use_ocr=use_ocr)

    def pause(self) -> None:
        self.engine.pause()

    def resume(self) -> None:
        if self.engine.is_busy():
            self.engine.resume()
        else:
            self.resume_queue()

    def stop(self) -> None:
        self.engine.stop()
        self.scanner.stop()

    def next_site(self) -> None:
        if not self.engine.is_busy():
            raise RuntimeError("No website crawl is running.")
        self.engine.skip_site()

    def clear_session(self) -> None:
        QueueManager(self.db).abandon_all_unfinished()
        self._append_log("Cleared saved URLs and pending resume queue.")

    def snapshot(self) -> dict[str, Any]:
        progress = _progress_dict(self.engine.progress)
        if self.scanner.is_busy() and progress["status"] in {"Idle", "Finished", ""}:
            progress["status"] = "Scanning folder"
        queue = QueueManager(self.db)
        resumable = [
            {"id": item.id, "url": item.url, "domain": item.domain, "status": item.status}
            for item in queue.list_resumable()
        ]
        with self._log_lock:
            lines = list(self.log)[-400:]
        return {
            "busy": self.is_busy(),
            "control_state": self.engine.control_state(),
            "light_mode": bool(self.settings().contact_scan_only),
            "output_folder": str(self.output),
            "progress": progress,
            "resumable": resumable,
            "log": lines,
            "settings": self.settings().to_dict(),
            "version": "1.4.2",
        }

    def list_sites(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT q.id, q.url, q.domain, q.status, q.output_root, q.error, "
            "q.started_at, q.finished_at, "
            "(SELECT COUNT(*) FROM emails e WHERE e.site_id = q.id) AS email_count, "
            "(SELECT COUNT(*) FROM phones p WHERE p.site_id = q.id) AS phone_count, "
            "(SELECT COUNT(*) FROM downloads d WHERE d.site_id = q.id) AS file_count, "
            "(SELECT COUNT(*) FROM visited_pages v WHERE v.site_id = q.id) AS page_count "
            "FROM queue_items q ORDER BY q.id DESC"
        )
        return rows

    def site_detail(self, site_id: int) -> dict[str, Any] | None:
        row = self.db.fetchone(
            "SELECT * FROM queue_items WHERE id = ?",
            (site_id,),
        )
        if row is None:
            return None
        emails = [r["email"] for r in self.db.fetchall(
            "SELECT email FROM emails WHERE site_id = ? ORDER BY email", (site_id,)
        )]
        phones = [r["phone"] for r in self.db.fetchall(
            "SELECT phone FROM phones WHERE site_id = ? ORDER BY phone", (site_id,)
        )]
        pages = self.db.fetchall(
            "SELECT url, status_code FROM visited_pages WHERE site_id = ? ORDER BY id DESC LIMIT 400",
            (site_id,),
        )
        files = self.db.fetchall(
            "SELECT url, file_path, file_type FROM downloads WHERE site_id = ? ORDER BY id DESC LIMIT 400",
            (site_id,),
        )
        domain = row.get("domain") or ""
        site_dir = self.output / domain if domain else None
        emails_file = []
        phones_file = []
        if site_dir and site_dir.is_dir():
            ep = site_dir / "emails.txt"
            pp = site_dir / "phone_numbers.txt"
            if ep.exists():
                emails_file = [ln.strip() for ln in ep.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
            if pp.exists():
                phones_file = [ln.strip() for ln in pp.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
        return {
            **row,
            "emails": emails or emails_file,
            "phones": phones or phones_file,
            "pages": pages,
            "files": files,
        }


_sessions: dict[int, UserCrawlSession] = {}
_sessions_lock = threading.Lock()


def session_for(user_id: int) -> UserCrawlSession:
    with _sessions_lock:
        found = _sessions.get(user_id)
        if found is None:
            found = UserCrawlSession(user_id)
            _sessions[user_id] = found
        return found


def unpack_scan_zip(user_id: int, data: bytes, filename: str) -> Path:
    dest = _user_root(user_id) / "folder_scans" / Path(filename).stem
    if dest.exists():
        for child in dest.rglob("*"):
            if child.is_file():
                child.unlink()
    dest.mkdir(parents=True, exist_ok=True)
    tmp = dest / (filename or "upload.zip")
    tmp.write_bytes(data)
    if zipfile.is_zipfile(tmp):
        with zipfile.ZipFile(tmp) as zf:
            zf.extractall(dest)
        tmp.unlink(missing_ok=True)
    return dest


def settings_payload(settings: AppSettings) -> dict[str, Any]:
    data = asdict(settings)
    data.pop("last_urls", None)
    return data
