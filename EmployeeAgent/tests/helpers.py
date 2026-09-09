from __future__ import annotations

from datetime import datetime, timezone

from app.status.events import EventType


def types(service) -> list[str]:
    return [event.event_type.value for event in service.engine.events]


def event_at(service, event_type: str) -> datetime | None:
    for event in service.engine.events:
        if event.event_type.value == event_type:
            return event.timestamp
    return None


def dt(hour: int, minute: int, second: int) -> datetime:
    return datetime(2026, 9, 9, hour, minute, second, tzinfo=timezone.utc)
