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
    frontier.flush()
    assert frontier.count() == 2

    rows = frontier.load_all()
    assert rows[0][0].rstrip("/").endswith("/a")
    assert bool(rows[0][2]) is True
    assert rows[1][0].rstrip("/").endswith("/b")

    frontier.remove("https://example.com/a/")
    frontier.flush()
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
    frontier.flush()
    dup = DuplicateManager(db, site_id)
    dup.mark_visited("https://clear.example/page")
    dup.clear_crawl_state(clear_contacts=True)
    frontier.clear()
    assert FrontierStore(db, site_id).count() == 0
    assert dup.visited_count == 0


def test_connectivity_error_detection():
    assert is_connectivity_error("ConnectTimeout: timed out")
    assert is_connectivity_error("getaddrinfo failed")
    assert is_connectivity_error("WinError 10060")
    assert not is_connectivity_error("HTTP 404 Not Found")
    assert not is_connectivity_error("certificate verify failed")
    assert not is_connectivity_error(None)


def test_start_new_batch_ignores_old_urls(tmp_path: Path):
    db = Database(tmp_path / "batch.db")
    qm = QueueManager(db)
    old = qm.enqueue_many(
        ["https://old.example", "https://also-old.example"],
        str(tmp_path / "out"),
    )
    qm.mark_running(old[0].id)
    frontier = FrontierStore(db, old[0].id)
    frontier.add("https://old.example/page", 1)
    frontier.flush()

    new_items = qm.start_new_batch(
        ["https://new.example"],
        str(tmp_path / "out2"),
    )
    assert len(new_items) == 1
    assert "new.example" in new_items[0].normalized_url
    assert qm.get(old[0].id).status == QueueStatus.CANCELLED.value
    assert qm.get(old[1].id).status == QueueStatus.CANCELLED.value
    pending = qm.next_pending()
    assert pending is not None
    assert "new.example" in pending.normalized_url
    # Only the new site should be pending
    assert qm.counts().get(QueueStatus.PENDING.value, 0) == 1
    assert FrontierStore(db, old[0].id).count() == 0


def test_prepare_resume_ignores_superseded_start_sites(tmp_path: Path):
    db = Database(tmp_path / "supersede.db")
    qm = QueueManager(db)
    old = qm.enqueue_many(["https://old-resume.example"], str(tmp_path / "out"))
    qm.mark_running(old[0].id)
    qm.start_new_batch(["https://fresh.example"], str(tmp_path / "out2"))
    # Superseded old site must not come back on Resume / auto-resume.
    assert qm.count_unfinished() == 1
    resumable = qm.list_resumable()
    assert len(resumable) == 1
    assert "fresh.example" in resumable[0].normalized_url
    qm.prepare_resume()
    assert qm.get(old[0].id).status == QueueStatus.CANCELLED.value
    assert "Superseded" in (qm.get(old[0].id).error or "")


def test_power_loss_running_site_is_resumable(tmp_path: Path):
    db = Database(tmp_path / "power.db")
    qm = QueueManager(db)
    items = qm.enqueue_many(
        ["https://a-power.example", "https://b-power.example"],
        str(tmp_path / "out"),
    )
    qm.mark_running(items[0].id)
    # Simulate reboot: Running becomes Pending, second site still Pending.
    assert qm.recover_interrupted() == 1
    assert qm.count_unfinished() == 2
    assert {i.normalized_url for i in qm.list_resumable()} == {
        items[0].normalized_url,
        items[1].normalized_url,
    }
