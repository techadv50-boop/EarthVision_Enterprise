"""URL queue manager with crash-resume support."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from webcrawler.db.database import Database, utcnow
from webcrawler.utils.url import get_registrable_domain, normalize_url


class QueueStatus(str, Enum):
    PENDING = "Pending"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


@dataclass
class QueueItem:
    id: int
    url: str
    normalized_url: str
    domain: str
    status: str
    output_root: str
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class QueueManager:
    """Maintain crawl queue state in SQLite."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def recover_interrupted(self) -> int:
        """Reset Running items to Pending after unexpected shutdown."""
        now = utcnow()
        with self.db.connection() as conn:
            cur = conn.execute(
                "UPDATE queue_items SET status = ?, updated_at = ?, error = COALESCE(error, ?) "
                "WHERE status = ?",
                (QueueStatus.PENDING.value, now, "Recovered after interruption", QueueStatus.RUNNING.value),
            )
            return cur.rowcount

    def prepare_resume(self) -> int:
        """Make unfinished work Pending again (power loss, offline, stop, errors)."""
        recovered = self.recover_interrupted()
        now = utcnow()
        with self.db.connection() as conn:
            cur = conn.execute(
                "UPDATE queue_items SET status = ?, updated_at = ?, "
                "error = COALESCE(error, ?) WHERE status IN (?, ?)",
                (
                    QueueStatus.PENDING.value,
                    now,
                    "Ready to resume",
                    QueueStatus.FAILED.value,
                    QueueStatus.CANCELLED.value,
                ),
            )
            return recovered + cur.rowcount

    def count_unfinished(self) -> int:
        """Count sites that Resume can continue (does not mutate)."""
        row = self.db.fetchone(
            "SELECT COUNT(*) AS c FROM queue_items WHERE status IN (?, ?, ?, ?)",
            (
                QueueStatus.PENDING.value,
                QueueStatus.RUNNING.value,
                QueueStatus.FAILED.value,
                QueueStatus.CANCELLED.value,
            ),
        )
        return int(row["c"]) if row else 0

    def mark_pending(self, item_id: int, error: str | None = None) -> None:
        """Leave a site unfinished so Resume can continue from the saved frontier."""
        now = utcnow()
        self.db.execute(
            "UPDATE queue_items SET status=?, finished_at=NULL, updated_at=?, error=? WHERE id=?",
            (QueueStatus.PENDING.value, now, (error or "")[:2000] or None, item_id),
        )

    def clear_pending(self) -> None:
        self.db.execute(
            "DELETE FROM queue_items WHERE status IN (?, ?)",
            (QueueStatus.PENDING.value, QueueStatus.CANCELLED.value),
        )

    def start_new_batch(self, urls: Iterable[str], output_root: str) -> list[QueueItem]:
        """Start button: queue exactly these URLs from scratch (ignore old unfinished)."""
        from webcrawler.db.duplicates import DuplicateManager

        now = utcnow()
        with self.db.connection() as conn:
            # Park every unfinished site so the run loop only sees the new list.
            conn.execute(
                "UPDATE queue_items SET status = ?, updated_at = ?, "
                "error = ? WHERE status IN (?, ?, ?, ?)",
                (
                    QueueStatus.CANCELLED.value,
                    now,
                    "Superseded by new Start",
                    QueueStatus.PENDING.value,
                    QueueStatus.RUNNING.value,
                    QueueStatus.FAILED.value,
                    QueueStatus.CANCELLED.value,
                ),
            )
            # Drop saved frontiers for superseded sites (listed sites are cleared below).
            conn.execute(
                "DELETE FROM frontier WHERE site_id IN "
                "(SELECT id FROM queue_items WHERE status = ? AND error = ?)",
                (QueueStatus.CANCELLED.value, "Superseded by new Start"),
            )

        items = self.enqueue_many(urls, output_root)
        for item in items:
            # Start = from scratch for each listed site.
            DuplicateManager(self.db, item.id).clear_crawl_state(clear_contacts=True)
            self.db.execute(
                "UPDATE queue_items SET error=NULL, started_at=NULL, finished_at=NULL, "
                "updated_at=? WHERE id=?",
                (now, item.id),
            )
        return items

    def enqueue_many(self, urls: Iterable[str], output_root: str) -> list[QueueItem]:
        items: list[QueueItem] = []
        now = utcnow()
        for url in urls:
            normalized = normalize_url(url)
            domain = get_registrable_domain(url)
            with self.db.connection() as conn:
                existing = conn.execute(
                    "SELECT * FROM queue_items WHERE normalized_url = ?",
                    (normalized,),
                ).fetchone()
                if existing and existing["status"] in {
                    QueueStatus.PENDING.value,
                    QueueStatus.RUNNING.value,
                }:
                    items.append(self._row_to_item(existing))
                    continue
                if existing and existing["status"] == QueueStatus.COMPLETED.value:
                    # Re-queue completed sites only if explicitly added again:
                    # update back to Pending for a fresh run.
                    conn.execute(
                        "UPDATE queue_items SET status=?, output_root=?, error=NULL, "
                        "started_at=NULL, finished_at=NULL, updated_at=? WHERE id=?",
                        (QueueStatus.PENDING.value, output_root, now, existing["id"]),
                    )
                    row = conn.execute(
                        "SELECT * FROM queue_items WHERE id = ?", (existing["id"],)
                    ).fetchone()
                    items.append(self._row_to_item(row))
                    continue
                if existing:
                    conn.execute(
                        "UPDATE queue_items SET status=?, output_root=?, error=NULL, "
                        "started_at=NULL, finished_at=NULL, updated_at=? WHERE id=?",
                        (QueueStatus.PENDING.value, output_root, now, existing["id"]),
                    )
                    row = conn.execute(
                        "SELECT * FROM queue_items WHERE id = ?", (existing["id"],)
                    ).fetchone()
                    items.append(self._row_to_item(row))
                    continue
                cur = conn.execute(
                    "INSERT INTO queue_items "
                    "(url, normalized_url, domain, status, output_root, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        url,
                        normalized,
                        domain,
                        QueueStatus.PENDING.value,
                        output_root,
                        now,
                        now,
                    ),
                )
                site_id = cur.lastrowid
                conn.execute(
                    "INSERT OR IGNORE INTO site_stats (site_id) VALUES (?)",
                    (site_id,),
                )
                row = conn.execute(
                    "SELECT * FROM queue_items WHERE id = ?", (site_id,)
                ).fetchone()
                items.append(self._row_to_item(row))
        return items

    def next_pending(self) -> QueueItem | None:
        row = self.db.fetchone(
            "SELECT * FROM queue_items WHERE status = ? ORDER BY id ASC LIMIT 1",
            (QueueStatus.PENDING.value,),
        )
        return self._row_to_item(row) if row else None

    def mark_running(self, item_id: int) -> None:
        now = utcnow()
        self.db.execute(
            "UPDATE queue_items SET status=?, started_at=?, updated_at=? WHERE id=?",
            (QueueStatus.RUNNING.value, now, now, item_id),
        )
        self.db.execute(
            "INSERT OR IGNORE INTO site_stats (site_id) VALUES (?)",
            (item_id,),
        )

    def mark_completed(self, item_id: int) -> None:
        now = utcnow()
        self.db.execute(
            "UPDATE queue_items SET status=?, finished_at=?, updated_at=?, error=NULL WHERE id=?",
            (QueueStatus.COMPLETED.value, now, now, item_id),
        )

    def mark_failed(self, item_id: int, error: str) -> None:
        now = utcnow()
        self.db.execute(
            "UPDATE queue_items SET status=?, finished_at=?, updated_at=?, error=? WHERE id=?",
            (QueueStatus.FAILED.value, now, now, error[:2000], item_id),
        )

    def cancel_remaining(self) -> int:
        now = utcnow()
        with self.db.connection() as conn:
            cur = conn.execute(
                "UPDATE queue_items SET status=?, updated_at=? WHERE status IN (?, ?)",
                (
                    QueueStatus.CANCELLED.value,
                    now,
                    QueueStatus.PENDING.value,
                    QueueStatus.RUNNING.value,
                ),
            )
            return cur.rowcount

    def counts(self) -> dict[str, int]:
        rows = self.db.fetchall(
            "SELECT status, COUNT(*) AS c FROM queue_items GROUP BY status"
        )
        result = {s.value: 0 for s in QueueStatus}
        for row in rows:
            result[row["status"]] = row["c"]
        return result

    def list_items(self) -> list[QueueItem]:
        rows = self.db.fetchall("SELECT * FROM queue_items ORDER BY id ASC")
        return [self._row_to_item(r) for r in rows]

    def get(self, item_id: int) -> QueueItem | None:
        row = self.db.fetchone("SELECT * FROM queue_items WHERE id = ?", (item_id,))
        return self._row_to_item(row) if row else None

    @staticmethod
    def _row_to_item(row) -> QueueItem:
        return QueueItem(
            id=row["id"],
            url=row["url"],
            normalized_url=row["normalized_url"],
            domain=row["domain"],
            status=row["status"],
            output_root=row["output_root"],
            error=row["error"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )
