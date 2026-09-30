"""Persisted per-site URL frontier for crash/power-loss resume."""

from __future__ import annotations

import threading

from webcrawler.db.database import Database
from webcrawler.utils.url import normalize_url


class FrontierStore:
    """Disk-backed URL queue with batched writes (keeps crawl speed high)."""

    def __init__(self, db: Database, site_id: int) -> None:
        self.db = db
        self.site_id = site_id
        self._lock = threading.Lock()
        # normalized -> (url, depth, priority_rank)  lower rank = sooner
        self._pending_adds: dict[str, tuple[str, int, int]] = {}
        self._pending_removes: set[str] = set()

    def clear(self) -> None:
        with self._lock:
            self._pending_adds.clear()
            self._pending_removes.clear()
        self.db.execute("DELETE FROM frontier WHERE site_id = ?", (self.site_id,))

    def add(self, url: str, depth: int, priority: bool | int = False) -> bool:
        normalized = normalize_url(url)
        if not normalized:
            return False
        if isinstance(priority, bool):
            rank = 1 if priority else 6
        else:
            rank = int(priority)
        with self._lock:
            self._pending_removes.discard(normalized)
            prev = self._pending_adds.get(normalized)
            if prev is not None:
                rank = min(prev[2], rank)
                depth = min(prev[1], depth)
                url = prev[0]
            self._pending_adds[normalized] = (url, depth, rank)
            if len(self._pending_adds) + len(self._pending_removes) >= 10:
                self._flush_unlocked()
        return True

    def remove(self, url: str) -> None:
        normalized = normalize_url(url)
        with self._lock:
            self._pending_adds.pop(normalized, None)
            self._pending_removes.add(normalized)
            if len(self._pending_removes) >= 10:
                self._flush_unlocked()

    def flush(self) -> None:
        with self._lock:
            self._flush_unlocked()

    def _flush_unlocked(self) -> None:
        removes = list(self._pending_removes)
        adds = list(self._pending_adds.items())
        self._pending_removes.clear()
        self._pending_adds.clear()
        if not removes and not adds:
            return
        try:
            with self.db.connection() as conn:
                if removes:
                    conn.executemany(
                        "DELETE FROM frontier WHERE site_id = ? AND normalized_url = ?",
                        [(self.site_id, n) for n in removes],
                    )
                if adds:
                    conn.executemany(
                        "INSERT INTO frontier "
                        "(site_id, url, normalized_url, depth, priority) "
                        "VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT(site_id, normalized_url) DO UPDATE SET "
                        "priority = MIN(frontier.priority, excluded.priority), "
                        "depth = MIN(frontier.depth, excluded.depth)",
                        [
                            (self.site_id, url, normalized, depth, priority)
                            for normalized, (url, depth, priority) in adds
                        ],
                    )
        except Exception:
            for n in removes:
                self._pending_removes.add(n)
            for normalized, payload in adds:
                if normalized not in self._pending_removes:
                    self._pending_adds[normalized] = payload

    def count(self) -> int:
        self.flush()
        row = self.db.fetchone(
            "SELECT COUNT(*) AS c FROM frontier WHERE site_id = ?",
            (self.site_id,),
        )
        return int(row["c"]) if row else 0

    def load_all(self) -> list[tuple[str, int, int]]:
        """Return (url, depth, priority_rank) with lower rank first."""
        self.flush()
        rows = self.db.fetchall(
            "SELECT url, depth, priority FROM frontier WHERE site_id = ? "
            "ORDER BY priority ASC, id ASC",
            (self.site_id,),
        )
        return [(r["url"], int(r["depth"]), int(r["priority"])) for r in rows]

    def drop_visited(self) -> int:
        """Remove frontier rows that were already crawled."""
        self.flush()
        with self.db.connection() as conn:
            cur = conn.execute(
                "DELETE FROM frontier WHERE site_id = ? AND normalized_url IN ("
                "SELECT normalized_url FROM visited_pages WHERE site_id = ?"
                ")",
                (self.site_id, self.site_id),
            )
            return int(cur.rowcount or 0)

    def count_pending(self) -> int:
        """Frontier URLs that have not been visited yet."""
        self.flush()
        row = self.db.fetchone(
            "SELECT COUNT(*) AS c FROM frontier f "
            "WHERE f.site_id = ? AND NOT EXISTS ("
            "  SELECT 1 FROM visited_pages v "
            "  WHERE v.site_id = f.site_id AND v.normalized_url = f.normalized_url"
            ")",
            (self.site_id,),
        )
        return int(row["c"]) if row else 0

    def load_pending_batch(
        self, limit: int, skip: set[str] | None = None
    ) -> list[tuple[str, int, int]]:
        """Next unvisited frontier URLs, skipping ones already held in memory."""
        self.flush()
        if limit <= 0:
            return []
        skip = skip or set()
        fetch_n = min(50000, max(limit + len(skip) + 50, limit))
        rows = self.db.fetchall(
            "SELECT f.url, f.normalized_url, f.depth, f.priority FROM frontier f "
            "WHERE f.site_id = ? AND NOT EXISTS ("
            "  SELECT 1 FROM visited_pages v "
            "  WHERE v.site_id = f.site_id AND v.normalized_url = f.normalized_url"
            ") "
            "ORDER BY f.priority ASC, f.id ASC LIMIT ?",
            (self.site_id, fetch_n),
        )
        out: list[tuple[str, int, int]] = []
        for row in rows:
            if row["normalized_url"] in skip:
                continue
            out.append((row["url"], int(row["depth"]), int(row["priority"])))
            if len(out) >= limit:
                break
        return out
