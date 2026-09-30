"""SQLite database layer for queue and crawl metadata."""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from webcrawler.settings.manager import app_data_dir


SCHEMA = """
CREATE TABLE IF NOT EXISTS queue_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    normalized_url TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending',
    output_root TEXT NOT NULL,
    error TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS visited_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    status_code INTEGER,
    UNIQUE(site_id, normalized_url),
    FOREIGN KEY(site_id) REFERENCES queue_items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    sha256 TEXT,
    file_path TEXT,
    file_type TEXT,
    UNIQUE(site_id, normalized_url),
    FOREIGN KEY(site_id) REFERENCES queue_items(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_downloads_sha
    ON downloads(site_id, sha256) WHERE sha256 IS NOT NULL;

CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    UNIQUE(site_id, email),
    FOREIGN KEY(site_id) REFERENCES queue_items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS phones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL,
    phone TEXT NOT NULL,
    UNIQUE(site_id, phone),
    FOREIGN KEY(site_id) REFERENCES queue_items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS site_stats (
    site_id INTEGER PRIMARY KEY,
    pages_crawled INTEGER DEFAULT 0,
    documents_downloaded INTEGER DEFAULT 0,
    pdfs INTEGER DEFAULT 0,
    word_files INTEGER DEFAULT 0,
    excel_files INTEGER DEFAULT 0,
    powerpoint_files INTEGER DEFAULT 0,
    images INTEGER DEFAULT 0,
    emails INTEGER DEFAULT 0,
    phones INTEGER DEFAULT 0,
    FOREIGN KEY(site_id) REFERENCES queue_items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    must_change_password INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Persisted crawl frontier so power-loss / reboot can resume mid-site.
CREATE TABLE IF NOT EXISTS frontier (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    UNIQUE(site_id, normalized_url),
    FOREIGN KEY(site_id) REFERENCES queue_items(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_frontier_site_priority
    ON frontier(site_id, priority ASC, id ASC);

-- Last known position so Resume can report where a site stopped.
CREATE TABLE IF NOT EXISTS crawl_checkpoints (
    site_id INTEGER PRIMARY KEY,
    last_url TEXT,
    pages_visited INTEGER NOT NULL DEFAULT 0,
    frontier_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(site_id) REFERENCES queue_items(id) ON DELETE CASCADE
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Thread-safe SQLite access."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (app_data_dir() / "crawler.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=120)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 120000")
        conn.execute("PRAGMA synchronous = NORMAL")
        # Bound cache so a multi-day crawl does not grow without limit on Win7.
        conn.execute("PRAGMA cache_size = -16000")
        conn.execute("PRAGMA wal_autocheckpoint = 1000")
        return conn

    def _live(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._connect()
            return self._conn
        try:
            self._conn.execute("SELECT 1")
        except sqlite3.Error:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = self._connect()
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None

    def wal_checkpoint(self) -> None:
        """Keep the WAL from growing without bound during multi-hour crawls."""
        with self._lock:
            try:
                self._live().execute("PRAGMA wal_checkpoint(PASSIVE)")
            except sqlite3.Error:
                pass

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(SCHEMA)
                # Recreate frontier index: lower priority rank must come first.
                conn.execute("DROP INDEX IF EXISTS idx_frontier_site_priority")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_frontier_site_priority "
                    "ON frontier(site_id, priority ASC, id ASC)"
                )
                conn.commit()
            finally:
                conn.close()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        # One long-lived connection per process. Opening a new connection for
        # every page exhausts Windows handles over a 6–12 hour crawl.
        with self._lock:
            conn = self._live()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def execute(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> int:
        last_err: Exception | None = None
        for attempt in range(5):
            try:
                with self.connection() as conn:
                    cur = conn.execute(sql, params)
                    return cur.lastrowid or 0
            except sqlite3.OperationalError as exc:
                last_err = exc
                if "locked" not in str(exc).lower():
                    raise
                time.sleep(0.05 * (attempt + 1))
        if last_err:
            raise last_err
        return 0

    def fetchone(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row is not None else None

    def fetchall(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[dict[str, Any]]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
