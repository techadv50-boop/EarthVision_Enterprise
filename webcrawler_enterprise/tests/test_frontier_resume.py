"""Frontier persistence + resume helpers."""

from pathlib import Path

from webcrawler.db.database import Database
from webcrawler.db.duplicates import DuplicateManager
from webcrawler.db.frontier import FrontierStore
from webcrawler.queue.manager import QueueManager, QueueStatus
from webcrawler.utils.network import is_connectivity_error


def test_frontier_persists_and_restores(tmp_path: Path):
    db = Database(tmp_path / "frontier.db")
    qm = QueueManager(db)
    items = qm.enqueue_many(["https://example.com"], str(tmp_path / "out"))
    site_id = items[0].id
    frontier = FrontierStore(db, site_id)

    assert frontier.add("https://example.com/a", 1, priority=True)
    assert frontier.add("https://example.com/b", 2, priority=False)
    assert frontier.add("https://example.com/a", 9, priority=False)  # ignore dup
    assert frontier.count() == 2

    rows = frontier.load_all()
    assert rows[0][0].endswith("/a")
    assert rows[0][2] is True
    assert rows[1][0].endswith("/b")

    frontier.remove("https://example.com/a/")
    assert frontier.count() == 1
    frontier.clear()
    assert frontier.count() == 0


def test_prepare_resume_recovers_failed_and_running(tmp_path: Path):
    db = Database(tmp_path / "queue.db")
    qm = QueueManager(db)
    items = qm.enqueue_many(
        ["https://a.example", "https://b.example"],
        str(tmp_path / "out"),
    )
    qm.mark_running(items[0].id)
    qm.mark_failed(items[1].id, "offline")
    recovered = qm.prepare_resume()
    assert recovered >= 2
    assert qm.get(items[0].id).status == QueueStatus.PENDING.value
    assert qm.get(items[1].id).status == QueueStatus.PENDING.value


def test_mark_pending_keeps_site_resumable(tmp_path: Path):
    db = Database(tmp_path / "pending.db")
    qm = QueueManager(db)
    items = qm.enqueue_many(["https://resume.example"], str(tmp_path / "out"))
    qm.mark_running(items[0].id)
    qm.mark_pending(items[0].id, "Interrupted while offline")
    item = qm.get(items[0].id)
    assert item.status == QueueStatus.PENDING.value
    assert "offline" in (item.error or "").lower()


def test_clear_crawl_state_clears_frontier(tmp_path: Path):
    db = Database(tmp_path / "clear.db")
    qm = QueueManager(db)
    items = qm.enqueue_many(["https://clear.example"], str(tmp_path / "out"))
    site_id = items[0].id
    frontier = FrontierStore(db, site_id)
    frontier.add("https://clear.example/page", 1)
    dup = DuplicateManager(db, site_id)
    dup.mark_visited("https://clear.example/page")
    dup.clear_crawl_state(clear_contacts=True)
    assert frontier.count() == 0
    assert dup.visited_count == 0


def test_connectivity_error_detection():
    assert is_connectivity_error("ConnectTimeout: timed out")
    assert is_connectivity_error("getaddrinfo failed")
    assert is_connectivity_error("WinError 10060")
    assert not is_connectivity_error("HTTP 404 Not Found")
    assert not is_connectivity_error(None)
