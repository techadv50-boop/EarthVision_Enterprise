"""SQLite record of folder snapshots, local copies, and completed forwards."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from relay.remote import RemoteFile


@dataclass(frozen=True)
class LocalCopy:
    source_id: str
    relative_path: str
    size: int
    mtime_key: str
    local_path: str
    downloaded_at: float
    expires_at: float


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self._conn.close()

    def migrate(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS observations (
                source_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_key TEXT NOT NULL,
                first_seen_at REAL NOT NULL,
                PRIMARY KEY (source_id, relative_path)
            );

            CREATE TABLE IF NOT EXISTS local_copies (
                source_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_key TEXT NOT NULL,
                local_path TEXT NOT NULL,
                downloaded_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                PRIMARY KEY (source_id, relative_path)
            );

            CREATE TABLE IF NOT EXISTS deliveries (
                source_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_key TEXT NOT NULL,
                destination_id TEXT NOT NULL,
                delivered_at REAL NOT NULL,
                PRIMARY KEY (
                    source_id, relative_path, size, mtime_key, destination_id
                )
            );
            """
        )
        self._conn.commit()

    def note_observation(
        self,
        source_id: str,
        item: RemoteFile,
        now: float,
        stability_seconds: float,
    ) -> bool:
        """Remember this snapshot of one file. Return True when it is stable."""
        key = item.version_key
        row = self._conn.execute(
            """
            SELECT size, mtime_key, first_seen_at
            FROM observations
            WHERE source_id = ? AND relative_path = ?
            """,
            (source_id, item.relative_path),
        ).fetchone()
        if row is None or row["size"] != item.size or row["mtime_key"] != key:
            self._conn.execute(
                """
                INSERT INTO observations (
                    source_id, relative_path, size, mtime_key, first_seen_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (source_id, relative_path) DO UPDATE SET
                    size = excluded.size,
                    mtime_key = excluded.mtime_key,
                    first_seen_at = excluded.first_seen_at
                """,
                (source_id, item.relative_path, item.size, key, now),
            )
            self._conn.commit()
            return stability_seconds <= 0
        return (now - float(row["first_seen_at"])) >= stability_seconds

    def forget_missing_observations(self, source_id: str, present: set[str]) -> None:
        rows = self._conn.execute(
            "SELECT relative_path FROM observations WHERE source_id = ?",
            (source_id,),
        ).fetchall()
        stale = [row["relative_path"] for row in rows if row["relative_path"] not in present]
        if not stale:
            return
        self._conn.executemany(
            "DELETE FROM observations WHERE source_id = ? AND relative_path = ?",
            [(source_id, path) for path in stale],
        )
        self._conn.commit()

    def is_delivered(self, source_id: str, item: RemoteFile, destination_id: str) -> bool:
        row = self._conn.execute(
            """
            SELECT 1 FROM deliveries
            WHERE source_id = ? AND relative_path = ? AND size = ?
              AND mtime_key = ? AND destination_id = ?
            """,
            (source_id, item.relative_path, item.size, item.version_key, destination_id),
        ).fetchone()
        return row is not None

    def mark_delivered(
        self,
        source_id: str,
        item: RemoteFile,
        destination_id: str,
        delivered_at: float,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO deliveries (
                source_id, relative_path, size, mtime_key, destination_id, delivered_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (
                source_id, relative_path, size, mtime_key, destination_id
            ) DO UPDATE SET delivered_at = excluded.delivered_at
            """,
            (
                source_id,
                item.relative_path,
                item.size,
                item.version_key,
                destination_id,
                delivered_at,
            ),
        )
        self._conn.commit()

    def get_local(self, source_id: str, relative_path: str) -> LocalCopy | None:
        row = self._conn.execute(
            """
            SELECT source_id, relative_path, size, mtime_key, local_path,
                   downloaded_at, expires_at
            FROM local_copies
            WHERE source_id = ? AND relative_path = ?
            """,
            (source_id, relative_path),
        ).fetchone()
        if row is None:
            return None
        return LocalCopy(
            source_id=row["source_id"],
            relative_path=row["relative_path"],
            size=row["size"],
            mtime_key=row["mtime_key"],
            local_path=row["local_path"],
            downloaded_at=row["downloaded_at"],
            expires_at=row["expires_at"],
        )

    def save_local(
        self,
        source_id: str,
        item: RemoteFile,
        local_path: str,
        *,
        downloaded_at: float,
        expires_at: float,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO local_copies (
                source_id, relative_path, size, mtime_key, local_path,
                downloaded_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source_id, relative_path) DO UPDATE SET
                size = excluded.size,
                mtime_key = excluded.mtime_key,
                local_path = excluded.local_path,
                downloaded_at = excluded.downloaded_at,
                expires_at = excluded.expires_at
            """,
            (
                source_id,
                item.relative_path,
                item.size,
                item.version_key,
                local_path,
                downloaded_at,
                expires_at,
            ),
        )
        self._conn.commit()

    def expired_locals(self, now: float) -> list[LocalCopy]:
        rows = self._conn.execute(
            """
            SELECT source_id, relative_path, size, mtime_key, local_path,
                   downloaded_at, expires_at
            FROM local_copies
            WHERE expires_at <= ?
            """,
            (now,),
        ).fetchall()
        return [
            LocalCopy(
                source_id=row["source_id"],
                relative_path=row["relative_path"],
                size=row["size"],
                mtime_key=row["mtime_key"],
                local_path=row["local_path"],
                downloaded_at=row["downloaded_at"],
                expires_at=row["expires_at"],
            )
            for row in rows
        ]

    def delete_local(self, source_id: str, relative_path: str) -> None:
        self._conn.execute(
            "DELETE FROM local_copies WHERE source_id = ? AND relative_path = ?",
            (source_id, relative_path),
        )
        self._conn.commit()
