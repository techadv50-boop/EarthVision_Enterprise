from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from app.runtime.clock import Clock, RealClock
from app.runtime.persist import PersistedState
from app.status.events import (
    CLEAN_POWER_OFF,
    CONN_CONNECTED,
    CONN_CONNECTING,
    CONN_UNAVAILABLE,
    PRESENCE_ACTIVE,
    PRESENCE_INACTIVE,
    PRESENCE_LOCKED,
    PRESENCE_LOGGED_OUT,
    AuditEvent,
    EventType,
)
from app.status.hierarchy import tray_indicator, workstation_status


EventSink = Callable[[AuditEvent], None]


@dataclass
class StatusState:
    employee_id: str
    device_id: str
    presence: str = PRESENCE_LOGGED_OUT
    connection: str = CONN_CONNECTING
    lifecycle: str | None = None
    last_input_at: datetime | None = None
    last_server_communication: datetime | None = None
    last_local_tick_at: datetime | None = None
    boot_id: str | None = None
    config_error: str | None = None
    monitoring: bool = True
    last_idle_seconds: float | None = None

    def employee_status(self) -> str:
        return workstation_status(
            lifecycle=self.lifecycle,
            presence=self.presence,
            connection=self.connection,
            config_error=self.config_error,
        )

    def activity_status(self) -> str:
        return self.presence

    def tray_indicator(self) -> str:
        return tray_indicator(
            connection=self.connection,
            config_error=self.config_error,
            monitoring=self.monitoring,
        )


class StatusEngine:
    """Pure status machine. Platform events are injected; nothing is invented."""

    def __init__(
        self,
        employee_id: str,
        device_id: str,
        *,
        inactivity_timeout_seconds: float = 30,
        offline_after_seconds: float = 30,
        clock: Clock | None = None,
        on_event: EventSink | None = None,
    ) -> None:
        self.clock = clock or RealClock()
        self.inactivity_timeout_seconds = inactivity_timeout_seconds
        self.offline_after_seconds = offline_after_seconds
        self.on_event = on_event
        self.state = StatusState(employee_id=employee_id, device_id=device_id)
        self._online_emitted = False
        self._server_offline_emitted = False
        self._last_heartbeat_success_at: datetime | None = None
        self._last_heartbeat_attempt_at: datetime | None = None
        self._fail_started_at: datetime | None = None
        self._heartbeat_ok = False
        self._clean_power_off = False
        self._need_activity_event = False
        self.events: list[AuditEvent] = []

    def persist_record(self) -> PersistedState:
        last = self.events[-1] if self.events else None
        return PersistedState(
            boot_id=self.state.boot_id,
            last_event_type=last.event_type.value if last else None,
            last_event_at=last.timestamp if last else None,
            last_heartbeat_at=self._last_heartbeat_success_at or self.state.last_server_communication,
            last_local_tick_at=self.state.last_local_tick_at,
            presence=self.state.presence,
            connection=self.state.connection,
            clean_power_off=self._clean_power_off,
        )

    def recover_and_start(
        self,
        previous: PersistedState,
        *,
        boot_id: str,
        user_logged_in: bool,
        session_locked: bool,
    ) -> None:
        self.state.boot_id = boot_id
        self.state.connection = CONN_CONNECTING
        self.state.monitoring = True
        previous_boot = previous.boot_id
        last_event = previous.last_event_type

        expected_power_off = previous.clean_power_off or last_event in CLEAN_POWER_OFF
        if previous_boot and previous_boot != boot_id:
            if not expected_power_off:
                self._emit_unexpected(previous)
            self.on_startup(boot_id)
            if user_logged_in:
                self.on_login()
                if session_locked:
                    self.on_lock()
            return

        if previous_boot and previous_boot == boot_id:
            self._emit(EventType.AGENT_START)
            if last_event and not (previous.clean_power_off or last_event in CLEAN_POWER_OFF):
                self._emit_unexpected(previous, note="Agent stopped unexpectedly")
            self.state.lifecycle = None
            if user_logged_in:
                if session_locked:
                    self.state.presence = PRESENCE_LOCKED
                else:
                    self.state.presence = PRESENCE_ACTIVE
                    self._need_activity_event = True
                self._ensure_online()
            else:
                self.state.presence = PRESENCE_LOGGED_OUT
            return

        self.on_startup(boot_id)
        if user_logged_in:
            self.on_login()
            if session_locked:
                self.on_lock()

    def on_startup(self, boot_id: str) -> None:
        self.state.boot_id = boot_id
        self.state.lifecycle = "STARTUP"
        self.state.presence = PRESENCE_LOGGED_OUT
        self.state.connection = CONN_CONNECTING
        self._online_emitted = False
        self._server_offline_emitted = False
        self._heartbeat_ok = False
        self._clean_power_off = False
        self._need_activity_event = False
        self._emit(EventType.STARTUP, details={"boot_id": boot_id})

    def on_login(self) -> None:
        if self.state.presence == PRESENCE_LOCKED:
            return
        self.state.lifecycle = None
        self.state.presence = PRESENCE_ACTIVE
        self._need_activity_event = True
        self._emit(EventType.LOGIN)

    def on_logout(self) -> None:
        self.state.presence = PRESENCE_LOGGED_OUT
        self.state.lifecycle = None
        self._emit(EventType.LOGOUT)

    def on_lock(self) -> None:
        if self.state.presence == PRESENCE_LOGGED_OUT:
            return
        self.state.presence = PRESENCE_LOCKED
        self.state.lifecycle = None
        self._emit(EventType.LOCKED)

    def on_unlock(self) -> None:
        if self.state.presence != PRESENCE_LOCKED:
            return
        self._emit(EventType.UNLOCKED)
        idle = self.state.last_idle_seconds
        if idle is not None and idle >= self.inactivity_timeout_seconds:
            self.state.presence = PRESENCE_INACTIVE
            self._emit(EventType.INACTIVE, details=_idle_details(idle))
        else:
            self.state.presence = PRESENCE_ACTIVE
            self._emit(EventType.ACTIVE, details=_idle_details(idle))

    def on_shutdown(self, *, restart: bool = False) -> None:
        event = EventType.RESTART if restart else EventType.SHUTDOWN
        self.state.lifecycle = "SHUTDOWN"
        self._clean_power_off = True
        self._emit(event)
        self._emit(EventType.OFFLINE, details={"reason": event.value})
        self.state.connection = CONN_UNAVAILABLE
        self._server_offline_emitted = True
        self._online_emitted = False

    def on_activity_sample(self, idle_seconds: float) -> None:
        now = self.clock.now()
        self.state.last_local_tick_at = now
        self.state.last_idle_seconds = idle_seconds
        self.state.last_input_at = now
        if idle_seconds is not None:
            from datetime import timedelta

            self.state.last_input_at = now - timedelta(seconds=max(0.0, idle_seconds))
        if not self.state.monitoring:
            return
        if self.state.presence in (PRESENCE_LOCKED, PRESENCE_LOGGED_OUT):
            return
        if self.state.lifecycle == "SHUTDOWN":
            return
        if idle_seconds >= self.inactivity_timeout_seconds:
            if self.state.presence != PRESENCE_INACTIVE or self._need_activity_event:
                self.state.presence = PRESENCE_INACTIVE
                self._need_activity_event = False
                self._emit(EventType.INACTIVE, details=_idle_details(idle_seconds))
        else:
            if self.state.presence != PRESENCE_ACTIVE or self._need_activity_event:
                self.state.presence = PRESENCE_ACTIVE
                self._need_activity_event = False
                self._emit(EventType.ACTIVE, details=_idle_details(idle_seconds))

    def on_heartbeat_result(self, success: bool) -> None:
        now = self.clock.now()
        self._last_heartbeat_attempt_at = now
        if success:
            self._heartbeat_ok = True
            self._fail_started_at = None
            self._last_heartbeat_success_at = now
            self.state.last_server_communication = now
            self.state.connection = CONN_CONNECTED
            self._server_offline_emitted = False
            if self.state.presence != PRESENCE_LOGGED_OUT and self.state.lifecycle != "SHUTDOWN":
                self._ensure_online()
            return
        self._heartbeat_ok = False
        if self._fail_started_at is None:
            self._fail_started_at = now
        if self.state.connection == CONN_CONNECTED:
            self.state.connection = CONN_CONNECTING
        anchor = self._last_heartbeat_success_at or self._fail_started_at
        if (now - anchor).total_seconds() >= self.offline_after_seconds:
            self._mark_server_unavailable()
        elif self.state.connection != CONN_UNAVAILABLE:
            self.state.connection = CONN_CONNECTING

    def on_agent_exit(self) -> None:
        self.state.monitoring = False
        self._clean_power_off = True
        self._emit(EventType.AGENT_EXIT)
        self.state.lifecycle = None

    def set_config_error(self, message: str | None) -> None:
        self.state.config_error = message

    def _mark_server_unavailable(self) -> None:
        self.state.connection = CONN_UNAVAILABLE
        if not self._server_offline_emitted and self.state.lifecycle != "SHUTDOWN":
            self._emit(EventType.OFFLINE, details={"reason": "heartbeat_timeout"})
            self._server_offline_emitted = True
            self._online_emitted = False

    def _ensure_online(self) -> None:
        if self._online_emitted:
            return
        if self.state.presence == PRESENCE_LOGGED_OUT:
            return
        if self.state.lifecycle == "SHUTDOWN":
            return
        self._emit(EventType.ONLINE)
        self._online_emitted = True
        self._server_offline_emitted = False

    def _emit_unexpected(self, previous: PersistedState, note: str = "No shutdown event was recorded") -> None:
        stamp = previous.last_heartbeat_at or previous.last_local_tick_at or previous.last_event_at
        if stamp is None:
            # Still do not invent a shutdown time; skip a timed unexpected event.
            stamp = None
        details = {
            "note": note,
            "previous_state": previous.last_event_type or previous.presence,
            "used_last_heartbeat": previous.last_heartbeat_at is not None,
        }
        if stamp is None:
            return
        self._emit(
            EventType.UNEXPECTED_OFFLINE,
            at=stamp,
            approximate=True,
            details=details,
        )
        self._emit(
            EventType.UNEXPECTED_SHUTDOWN,
            at=stamp,
            approximate=True,
            details=details,
        )

    def _emit(
        self,
        event_type: EventType,
        at: datetime | None = None,
        *,
        approximate: bool = False,
        details: dict | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            timestamp=at or self.clock.now(),
            employee_id=self.state.employee_id,
            device_id=self.state.device_id,
            event_type=event_type,
            approximate=approximate,
            details=details or {},
        )
        self.events.append(event)
        if self.on_event:
            self.on_event(event)
        return event


def _idle_details(idle_seconds: float | None) -> dict:
    if idle_seconds is None:
        return {}
    return {"last_input_age_seconds": round(float(idle_seconds), 3)}
