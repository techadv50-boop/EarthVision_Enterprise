from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from app.constants import APP_ID
from app.heartbeat.protocol import build_heartbeat_payload, heartbeat_url
from app.runtime.clock import Clock, RealClock
from app.status.engine import StatusEngine

logger = logging.getLogger(APP_ID)

UrlOpen = Callable[..., Any]


@dataclass
class HeartbeatResult:
    ok: bool
    at: datetime
    status_code: int | None = None
    error: str | None = None


class HeartbeatClient:
    def __init__(
        self,
        server_url: str,
        *,
        timeout_seconds: float = 3.0,
        enabled: bool = True,
        urlopen: UrlOpen | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.server_url = server_url
        self.timeout_seconds = timeout_seconds
        self.enabled = enabled
        self._urlopen = urlopen or urllib.request.urlopen
        self.clock = clock or RealClock()
        self._last_sent_at: datetime | None = None

    def send(self, engine: StatusEngine) -> HeartbeatResult:
        now = self.clock.now()
        if not self.enabled:
            return HeartbeatResult(ok=True, at=now, status_code=204)
        payload = build_heartbeat_payload(
            employee_id=engine.state.employee_id,
            device_id=engine.state.device_id,
            employee_status=engine.state.employee_status(),
            activity_status=engine.state.activity_status(),
            connection_status=engine.state.connection,
            timestamp=now,
            last_input_age_seconds=engine.state.last_idle_seconds,
            boot_id=engine.state.boot_id,
        )
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            heartbeat_url(self.server_url),
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "EmployeeMonitoringAgent/1.0",
            },
            method="POST",
        )
        try:
            with self._urlopen(request, timeout=self.timeout_seconds) as response:
                code = getattr(response, "status", None) or response.getcode()
                ok = 200 <= int(code) < 300
                self._last_sent_at = now
                return HeartbeatResult(ok=ok, at=now, status_code=int(code))
        except urllib.error.HTTPError as exc:
            logger.warning("Heartbeat HTTP error: %s", exc.code)
            return HeartbeatResult(ok=False, at=now, status_code=int(exc.code), error=str(exc.code))
        except Exception as exc:
            logger.warning("Heartbeat failed: %s", exc.__class__.__name__)
            return HeartbeatResult(ok=False, at=now, error=exc.__class__.__name__)


class FakeHeartbeat:
    def __init__(self, *, succeed: bool = True, clock: Clock | None = None) -> None:
        self.succeed = succeed
        self.clock = clock or RealClock()
        self.sent = 0
        self.enabled = True

    def send(self, engine: StatusEngine) -> HeartbeatResult:
        self.sent += 1
        return HeartbeatResult(ok=self.succeed, at=self.clock.now(), status_code=200 if self.succeed else 503)
