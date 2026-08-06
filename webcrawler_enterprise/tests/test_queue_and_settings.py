"""Tests for queue and duplicate managers."""

from pathlib import Path

from webcrawler.db.database import Database
from webcrawler.db.duplicates import DuplicateManager
from webcrawler.queue.manager import QueueManager, QueueStatus
from webcrawler.settings.manager import AppSettings, SettingsManager


def test_queue_enqueue_and_resume(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    qm = QueueManager(db)
    items = qm.enqueue_many(
        ["https://www.harvard.edu", "https://www.mit.edu", "https://www.harvard.edu"],
        str(tmp_path / "out"),
    )
    # harvard deduped by normalized URL uniqueness across inserts in same batch
    assert len(items) >= 2
    first = qm.next_pending()
    assert first is not None
    qm.mark_running(first.id)
    assert qm.get(first.id).status == QueueStatus.RUNNING.value
    recovered = qm.recover_interrupted()
    assert recovered == 1
    assert qm.get(first.id).status == QueueStatus.PENDING.value


def test_duplicates(tmp_path: Path):
    db = Database(tmp_path / "dup.db")
    qm = QueueManager(db)
    items = qm.enqueue_many(["https://example.com"], str(tmp_path))
    site_id = items[0].id
    dup = DuplicateManager(db, site_id)
    assert dup.mark_visited("https://example.com/a")
    assert not dup.mark_visited("https://example.com/a/")
    assert dup.add_email("Info@Example.com")
    assert not dup.add_email("info@example.com")
    assert dup.mark_download("https://example.com/a.pdf", "abc", "/tmp/a.pdf", "PDF")
    assert dup.has_hash("abc")
    assert not dup.should_download("https://example.com/a.pdf")


def test_settings_persist(tmp_path: Path):
    path = tmp_path / "settings.json"
    mgr = SettingsManager(path)
    mgr.update(crawl_depth=7, max_pages_per_site=42, ignore_robots_txt=True)
    mgr2 = SettingsManager(path)
    assert mgr2.settings.crawl_depth == 7
    assert mgr2.settings.max_pages_per_site == 42
    assert mgr2.settings.ignore_robots_txt is True
    assert isinstance(mgr2.settings, AppSettings)
