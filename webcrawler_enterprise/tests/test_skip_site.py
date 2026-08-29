"""Next-site / skip-current-site queue helpers."""

from pathlib import Path

from webcrawler.engine.orchestrator import CrawlEngine
from webcrawler.queue.manager import QueueManager, QueueStatus
from webcrawler.db.database import Database


def test_next_pending_can_exclude_deferred_ids(tmp_path: Path):
    db = Database(tmp_path / "skip.db")
    qm = QueueManager(db)
    items = qm.enqueue_many(
        ["https://a.example", "https://b.example", "https://c.example"],
        str(tmp_path / "out"),
    )
    first = qm.next_pending(exclude_ids={items[0].id})
    assert first is not None
    assert first.id == items[1].id
    none_left = qm.next_pending(exclude_ids={items[0].id, items[1].id, items[2].id})
    assert none_left is None


def test_skip_site_sets_control_state_without_stopping():
    engine = CrawlEngine(db=Database(Path("/tmp/skip-engine.db")))
    with engine._state_lock:
        engine._state = "running"
    engine.skip_site()
    assert engine.control_state() == "skip_site"
    assert engine._clear_skip_flag() is True
    assert engine.control_state() == "running"


def test_skip_site_unpauses():
    engine = CrawlEngine(db=Database(Path("/tmp/skip-pause.db")))
    with engine._state_lock:
        engine._state = "paused"
    engine.skip_site()
    assert engine.control_state() == "skip_site"
    with engine._state_lock:
        assert engine._state == "running"
