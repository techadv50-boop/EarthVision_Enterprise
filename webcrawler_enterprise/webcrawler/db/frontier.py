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
        self._pending_adds: dict[str, tuple[str, int, int]] = {}
        self._pending_removes: set[str] = set()

    def clear(self) -> None:
        with self._lock:
            self._pending_adds.clear()
            self._pending_removes.clear()
        self.db.execute("DELETE FROM frontier WHERE site_id = ?", (self.site_id,))

    def add(self, url: str, depth: int, priority: bool = False) -> bool:
        normalized = normalize_url(url)
        if not normalized:
            return False
        with self._lock:
            self._pending_removes.discard(normalized)
            pri = 1 if priority else 0
            prev = self._pending_adds.get(normalized)
            if prev is not None:
                # Keep best priority / shallowest depth while still batched.
                pri = max(prev[2], pri)
                depth = min(prev[1], depth)
                url = prev[0]
            self._pending_adds[normalized] = (url, depth, pri)
            if len(self._pending_adds) + len(self._pending_removes) >= 40:
                self._flush_unlocked()
        return True

    def remove(self, url: str) -> None:
        normalized = normalize_url(url)
        with self._lock:
            self._pending_adds.pop(normalized, None)
            self._pending_removes.add(normalized)
            if len(self._pending_removes) >= 40:
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
                        "INSERT OR IGNORE INTO frontier "
                        "(site_id, url, normalized_url, depth, priority) "
                        "VALUES (?, ?, ?, ?, ?)",
                        [
                            (self.site_id, url, normalized, depth, priority)
                            for normalized, (url, depth, priority) in adds
                        ],
                    )
        except Exception:
            # Re-queue failed batch so a later flush / end-of-site can retry.
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

    def load_all(self) -> list[tuple[str, int, bool]]:
        self.flush()
        rows = self.db.fetchall(
            "SELECT url, depth, priority FROM frontier WHERE site_id = ? "
            "ORDER BY priority DESC, id ASC",
            (self.site_id,),
        )
        return [(r["url"], int(r["depth"]), bool(r["priority"])) for r in rows]
