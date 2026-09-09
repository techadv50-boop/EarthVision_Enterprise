from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.status.events import AuditEvent, EventType, parse_datetime


class AuditStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    employee_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    approximate INTEGER NOT NULL DEFAULT 0,
                    details TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")

    def append(self, event: AuditEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO events (ts, employee_id, device_id, event_type, approximate, details) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event.timestamp.isoformat(),
                    event.employee_id,
                    event.device_id,
                    event.event_type.value,
                    1 if event.approximate else 0,
                    json.dumps(event.details, separators=(",", ":")),
                ),
            )

    def list_events(
        self,
        *,
        employee_id: str | None = None,
        limit: int = 500,
    ) -> list[AuditEvent]:
        sql = "SELECT ts, employee_id, device_id, event_type, approximate, details FROM events"
        params: list[object] = []
        if employee_id:
            sql += " WHERE employee_id = ?"
            params.append(employee_id)
        sql += " ORDER BY id ASC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        events: list[AuditEvent] = []
        for row in rows:
            details = json.loads(row["details"] or "{}")
            events.append(
                AuditEvent(
                    timestamp=parse_datetime(row["ts"]) or datetime.fromisoformat(row["ts"]),
                    employee_id=row["employee_id"],
                    device_id=row["device_id"],
                    event_type=EventType(row["event_type"]),
                    approximate=bool(row["approximate"]),
                    details=details if isinstance(details, dict) else {},
                )
            )
        return events
