"""Persisted per-site URL frontier for crash/power-loss resume."""

from __future__ import annotations

from webcrawler.db.database import Database
from webcrawler.utils.url import normalize_url


class FrontierStore:
    """Disk-backed URL queue. Entries stay until the URL is finished/skipped."""

    def __init__(self, db: Database, site_id: int) -> None:
        self.db = db
        self.site_id = site_id

    def clear(self) -> None:
        self.db.execute("DELETE FROM frontier WHERE site_id = ?", (self.site_id,))

    def add(self, url: str, depth: int, priority: bool = False) -> bool:
        normalized = normalize_url(url)
        if not normalized:
            return False
        try:
            self.db.execute(
                "INSERT OR IGNORE INTO frontier "
                "(site_id, url, normalized_url, depth, priority) VALUES (?, ?, ?, ?, ?)",
                (self.site_id, url, normalized, depth, 1 if priority else 0),
            )
            return True
        except Exception:
            return False

    def remove(self, url: str) -> None:
        normalized = normalize_url(url)
        self.db.execute(
            "DELETE FROM frontier WHERE site_id = ? AND normalized_url = ?",
            (self.site_id, normalized),
        )

    def count(self) -> int:
        row = self.db.fetchone(
            "SELECT COUNT(*) AS c FROM frontier WHERE site_id = ?",
            (self.site_id,),
        )
        return int(row["c"]) if row else 0

    def load_all(self) -> list[tuple[str, int, bool]]:
        rows = self.db.fetchall(
            "SELECT url, depth, priority FROM frontier WHERE site_id = ? "
            "ORDER BY priority DESC, id ASC",
            (self.site_id,),
        )
        return [(r["url"], int(r["depth"]), bool(r["priority"])) for r in rows]
