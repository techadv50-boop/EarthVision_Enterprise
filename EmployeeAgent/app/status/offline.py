from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.status.events import AuditEvent, EventType, to_iso


@dataclass(frozen=True)
class OfflinePeriod:
    start: datetime
    end: datetime
    kind: str
    approximate_start: bool
    employee_id: str
    device_id: str

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def as_dict(self) -> dict:
        return {
            "start": to_iso(self.start),
            "end": to_iso(self.end),
            "kind": self.kind,
            "approximate_start": self.approximate_start,
            "duration_seconds": int(self.duration.total_seconds()),
            "employee_id": self.employee_id,
            "device_id": self.device_id,
        }


def format_duration(delta: timedelta) -> str:
    total = int(round(delta.total_seconds()))
    if total < 0:
        total = 0
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if minutes or hours:
        parts.append(f"{minutes} minute" + ("s" if minutes != 1 else ""))
    parts.append(f"{seconds} second" + ("s" if seconds != 1 else ""))
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} {parts[1]}"
    return f"{parts[0]} {parts[1]} {parts[2]}"


_OFFLINE_START = {
    EventType.SHUTDOWN,
    EventType.RESTART,
    EventType.OFFLINE,
    EventType.UNEXPECTED_OFFLINE,
    EventType.UNEXPECTED_SHUTDOWN,
}


def compute_offline_periods(events: list[AuditEvent]) -> list[OfflinePeriod]:
    """Pair an offline/shutdown marker with the next STARTUP.

    Unexpected gaps use the last heartbeat (approximate) and never invent a
    shutdown timestamp.
    """
    periods: list[OfflinePeriod] = []
    pending: AuditEvent | None = None
    pending_kind = "OFFLINE"
    for event in events:
        if event.event_type in _OFFLINE_START:
            if pending is None or event.timestamp <= pending.timestamp:
                pending = event
                if event.event_type in (EventType.UNEXPECTED_OFFLINE, EventType.UNEXPECTED_SHUTDOWN):
                    pending_kind = "UNEXPECTED_OFFLINE"
                elif event.event_type in (EventType.SHUTDOWN, EventType.RESTART):
                    pending_kind = event.event_type.value
                else:
                    pending_kind = "OFFLINE"
        elif event.event_type == EventType.STARTUP and pending is not None:
            periods.append(
                OfflinePeriod(
                    start=pending.timestamp,
                    end=event.timestamp,
                    kind=pending_kind,
                    approximate_start=pending.approximate,
                    employee_id=event.employee_id,
                    device_id=event.device_id,
                )
            )
            pending = None
    return periods
