from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config.paths import resolve_paths
from app.config.schema import AgentConfig
from app.config.store import ConfigStore
from app.heartbeat.client import FakeHeartbeat
from app.platform.stub import StubPlatform
from app.runtime.clock import FakeClock
from app.security.password import hash_password
from app.service.agent import AgentService


@pytest.fixture(autouse=True)
def _fast_password(monkeypatch):
    monkeypatch.setenv("EMPLOYEE_AGENT_PBKDF2_ITERATIONS", "1000")
    monkeypatch.setenv("LOCALAPPDATA", "")  # force resolve_paths to use provided root


@pytest.fixture
def password() -> str:
    return "agent-pass-123"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 9, 9, 8, 29, 55, tzinfo=timezone.utc))


@pytest.fixture
def platform() -> StubPlatform:
    plat = StubPlatform()
    plat.logged_in = True
    plat.locked = False
    plat.idle = 0.0
    plat.set_boot_id("boot-1")
    return plat


def build_service(
    tmp_path: Path,
    clock: FakeClock,
    platform: StubPlatform,
    password: str,
    *,
    heartbeat: FakeHeartbeat | None = None,
    logged_in: bool | None = None,
    **config_kw,
) -> AgentService:
    if logged_in is not None:
        platform.logged_in = logged_in
    paths = resolve_paths(tmp_path / "agent-data")
    paths.ensure()
    fields = {
        "employee_id": "12",
        "device_id": "EMP12-PC",
        "password_hash": hash_password(password),
        "server_url": "http://127.0.0.1:9",
        "inactivity_timeout_seconds": 30,
        "heartbeat_interval_seconds": 10,
        "offline_after_seconds": 30,
        "start_with_windows": True,
    }
    fields.update(config_kw)
    config = AgentConfig(**fields)
    ConfigStore(paths.config_file).save(config)
    hb = heartbeat if heartbeat is not None else FakeHeartbeat(succeed=True, clock=clock)
    return AgentService(paths, config, platform, clock=clock, heartbeat=hb)


@pytest.fixture
def service(tmp_path, clock, platform, password) -> AgentService:
    return build_service(tmp_path, clock, platform, password)
