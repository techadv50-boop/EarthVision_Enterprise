"""SQLite database layer for queue and crawl metadata."""

from __future__ import annotations

import sqlite3
import threading
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
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Thread-safe SQLite access."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (app_data_dir() / "crawler.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=60)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(SCHEMA)
                conn.commit()
            finally:
                conn.close()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def execute(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> int:
        with self.connection() as conn:
            cur = conn.execute(sql, params)
            return cur.lastrowid or 0

    def fetchone(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> sqlite3.Row | None:
        with self.connection() as conn:
            return conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return list(conn.execute(sql, params).fetchall())
