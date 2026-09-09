"""Activity sampling without recording input content or coordinates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.platform.base import Platform
from app.runtime.clock import Clock, RealClock


@dataclass(frozen=True)
class ActivitySample:
    sampled_at: datetime
    idle_seconds: float

    def allowed_fields(self) -> tuple[str, ...]:
        return ("sampled_at", "idle_seconds")


class ActivityMonitor:
    """Uses last-input age only. Never records keys, clicks, or cursor positions."""

    def __init__(self, platform: Platform, clock: Clock | None = None) -> None:
        self.platform = platform
        self.clock = clock or RealClock()

    def sample(self) -> ActivitySample:
        idle = max(0.0, float(self.platform.idle_seconds()))
        return ActivitySample(sampled_at=self.clock.now(), idle_seconds=idle)
