from __future__ import annotations

import logging
import os
import threading
from datetime import datetime

from app.audit.store import AuditStore
from app.config.paths import AgentPaths
from app.config.schema import AgentConfig
from app.config.store import ConfigStore
from app.constants import APP_ID
from app.heartbeat.client import FakeHeartbeat, HeartbeatClient
from app.monitoring.activity import ActivityMonitor
from app.platform.base import Platform
from app.runtime.clock import Clock, RealClock
from app.runtime.logging import setup_logging
from app.runtime.persist import PersistedState, StateStore
from app.runtime.status_file import AgentStatusSnapshot, StatusFile
from app.service.controller import AccessController
from app.startup.registration import StartupManager
from app.status.engine import StatusEngine
from app.status.events import AuditEvent, EventType

logger = logging.getLogger(APP_ID)


class AgentService:
    """Background monitoring. Closing the dashboard must not stop this service."""

    def __init__(
        self,
        paths: AgentPaths,
        config: AgentConfig,
        platform: Platform,
        *,
        clock: Clock | None = None,
        heartbeat: HeartbeatClient | FakeHeartbeat | None = None,
        auto_heartbeat: bool = True,
    ) -> None:
        self.paths = paths
        self.config = config
        self.platform = platform
        self.clock = clock or RealClock()
        self.audit = AuditStore(paths.audit_db)
        self.state_store = StateStore(paths.state_file)
        self.status_file = StatusFile(paths.status_file)
        self.access = AccessController(config.password_hash)
        self.startup = StartupManager(platform)
        self.activity = ActivityMonitor(platform, clock=self.clock)
        self.engine = StatusEngine(
            config.employee_id or "unassigned",
            config.device_id,
            inactivity_timeout_seconds=config.inactivity_timeout_seconds,
            offline_after_seconds=config.offline_after_seconds,
            clock=self.clock,
            on_event=self._on_event,
        )
        self.heartbeat = heartbeat or HeartbeatClient(
            config.server_url,
            enabled=config.heartbeat_enabled,
            clock=self.clock,
        )
        self.auto_heartbeat = auto_heartbeat
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_heartbeat_at: datetime | None = None
        self.started = False
        self.exited = False

    def start(self) -> None:
        with self._lock:
            if self.started:
                return
            self.paths.ensure()
            setup_logging(self.paths.log_file)
            previous = self.state_store.load()
            self.engine.recover_and_start(
                previous,
                boot_id=self.platform.boot_id(),
                user_logged_in=self.platform.user_logged_in(),
                session_locked=self.platform.session_locked(),
            )
            if self.config.start_with_windows:
                result = self.startup.apply(True)
                if not result.ok:
                    message = result.error or "Startup registration failed"
                    logger.error("Windows startup registration failed: %s", message)
                    self.engine.set_config_error(message)
            self.platform.notify_session(self._on_session)
            self.platform.notify_power(self._on_power)
            self.started = True
            self.state_store.save(self.engine.persist_record())
            self._write_status()

    def start_background(self) -> None:
        self.start()
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="employee-agent-monitor", daemon=True)
        self._thread.start()

    def tick(self) -> None:
        if not self.started or self.exited:
            return
        due = False
        with self._lock:
            if self.auto_heartbeat:
                due = True
                if self._last_heartbeat_at is not None:
                    elapsed = (self.clock.now() - self._last_heartbeat_at).total_seconds()
                    due = elapsed >= self.config.heartbeat_interval_seconds
        if due:
            result = self.heartbeat.send(self.engine)
            with self._lock:
                self._last_heartbeat_at = self.clock.now()
                self.engine.on_heartbeat_result(result.ok)
        with self._lock:
            sample = self.activity.sample()
            self.engine.on_activity_sample(sample.idle_seconds)
            self.state_store.save(self.engine.persist_record())
            self._write_status()

    def request_exit(self, password: str) -> bool:
        if not self.access.authorize_exit(password):
            return False
        self.stop(record_exit=True)
        return True

    def stop(self, *, record_exit: bool = False) -> None:
        with self._lock:
            if record_exit and not self.exited:
                self.engine.on_agent_exit()
                self.state_store.save(self.engine.persist_record())
            self.exited = True
            self.engine.state.monitoring = False
            self._stop.set()
            self._write_status()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def close_dashboard(self) -> None:
        self.access.close_dashboard()

    def open_dashboard(self, password: str) -> bool:
        return self.access.open_dashboard(password)

    def is_monitoring(self) -> bool:
        return self.started and not self.exited and self.engine.state.monitoring

    def events(self) -> list[AuditEvent]:
        return self.audit.list_events()

    def save_config(self, config: AgentConfig) -> None:
        self.config = config
        self.engine.state.employee_id = config.employee_id
        self.engine.state.device_id = config.device_id
        self.engine.inactivity_timeout_seconds = config.inactivity_timeout_seconds
        self.engine.offline_after_seconds = config.offline_after_seconds
        ConfigStore(self.paths.config_file).save(config)
        if config.start_with_windows:
            result = self.startup.apply(True)
            if not result.ok:
                logger.error("Windows startup registration failed: %s", result.error)
                self.engine.set_config_error(result.error or "Startup registration failed")
        else:
            self.startup.apply(False)

    def _loop(self) -> None:
        interval = max(0.2, float(self.config.poll_interval_seconds))
        while not self._stop.wait(interval):
            try:
                self.tick()
            except Exception:
                logger.exception("Monitoring tick failed")

    def _on_event(self, event: AuditEvent) -> None:
        self.audit.append(event)
        logger.info(
            "event %s employee=%s device=%s",
            event.event_type.value,
            event.employee_id,
            event.device_id,
        )

    def _on_session(self, event: str) -> None:
        with self._lock:
            self._handle_session(event)
            self.state_store.save(self.engine.persist_record())
            self._write_status()

    def _on_power(self, event: str) -> None:
        with self._lock:
            self.engine.on_shutdown(restart=event == EventType.RESTART.value)
            self.state_store.save(self.engine.persist_record())
            self._write_status()

    def _handle_session(self, event: str) -> None:
        if event == "LOCKED":
            self.engine.on_lock()
        elif event == "UNLOCKED":
            self.engine.on_unlock()
        elif event == "LOGIN":
            self.engine.on_login()
        elif event == "LOGOUT":
            self.engine.on_logout()

    def _write_status(self) -> None:
        snap = AgentStatusSnapshot(
            running=self.is_monitoring(),
            pid=os.getpid(),
            employee_id=self.engine.state.employee_id,
            device_id=self.engine.state.device_id,
            employee_status=self.engine.state.employee_status(),
            activity_status=self.engine.state.activity_status(),
            connection_status=self.engine.state.connection,
            last_server_communication=self.engine.state.last_server_communication,
            monitoring=self.engine.state.monitoring,
            updated_at=self.clock.now(),
            config_error=self.engine.state.config_error,
        )
        self.status_file.write(snap)
