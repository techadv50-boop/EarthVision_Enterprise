"""Light contact-scan mode behavior."""

from pathlib import Path

import httpx

from webcrawler.db.database import Database
from webcrawler.db.duplicates import DuplicateManager
from webcrawler.downloader.file_downloader import FileDownloader
from webcrawler.logger.crawl_logger import CrawlLogger
from webcrawler.queue.manager import QueueManager
from webcrawler.settings.manager import AppSettings, SettingsManager


def test_contact_scan_only_default_true():
    assert AppSettings().contact_scan_only is True


def test_settings_persist_contact_scan(tmp_path: Path):
    path = tmp_path / "settings.json"
    mgr = SettingsManager(path)
    mgr.update(contact_scan_only=False)
    mgr2 = SettingsManager(path)
    assert mgr2.settings.contact_scan_only is False
    mgr2.update(contact_scan_only=True)
    assert SettingsManager(path).settings.contact_scan_only is True


def test_scan_extracts_contacts_without_saving(tmp_path: Path, monkeypatch):
    db = Database(tmp_path / "scan.db")
    qm = QueueManager(db)
    items = qm.enqueue_many(["https://scan.example"], str(tmp_path / "out"))
    dup = DuplicateManager(db, items[0].id)
    site_dir = tmp_path / "out" / "scan.example"
    site_dir.mkdir(parents=True)
    settings = AppSettings(contact_scan_only=True, retry_attempts=1)
    logger = CrawlLogger()
    downloader = FileDownloader(site_dir, settings, dup, logger, phone_region="US")

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/plain"}
        request = httpx.Request("GET", "https://scan.example/a.txt")

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):
            yield b"Contact us at light@scan.example or +1 (415) 555-0199"

    class FakeStream:
        def __enter__(self):
            return FakeResponse()

        def __exit__(self, *args):
            return False

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, *args, **kwargs):
            return FakeStream()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    ok = downloader.scan("https://scan.example/a.txt")
    assert ok is True
    assert "light@scan.example" in dup.emails
    # No document folders should be populated
    assert not any(site_dir.rglob("*.txt")) or list(site_dir.rglob("*.txt")) == []
    pdf_dir = site_dir / "PDF"
    assert not pdf_dir.exists() or not any(pdf_dir.iterdir())
