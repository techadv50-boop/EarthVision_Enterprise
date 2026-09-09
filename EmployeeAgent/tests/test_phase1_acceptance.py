"""Phase 1 demonstration checklist from the product requirements."""

from app.constants import ALREADY_RUNNING_MESSAGE
from app.platform.windows import WindowsPlatform, WTS_SESSION_LOCK, WTS_SESSION_LOGON, WTS_SESSION_LOGOFF, WTS_SESSION_UNLOCK
from app.runtime.instance import SingleInstanceLock
from tests.conftest import build_service
from tests.helpers import dt, types


def test_01_starts_with_windows_registration(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    assert platform.startup_enabled()
    assert "--background" in (platform.startup_command() or "")


def test_02_runs_in_background_without_dashboard(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    assert service.access.dashboard_open is False
    assert service.is_monitoring()


def test_03_status_file_lets_admin_see_running_state(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    data = service.status_file.read()
    assert data and data["running"] is True
    assert data["pid"]


def test_04_only_one_instance(tmp_path):
    lock_file = tmp_path / "agent.lock"
    a = SingleInstanceLock(lock_file)
    b = SingleInstanceLock(lock_file)
    assert a.acquire()
    assert b.acquire() is False
    assert b.message == ALREADY_RUNNING_MESSAGE
    a.release()


def test_05_and_06_password_required_every_dashboard_open(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    assert service.open_dashboard(password)
    service.close_dashboard()
    assert service.open_dashboard("nope") is False
    assert service.open_dashboard(password)


def test_07_closing_dashboard_keeps_monitoring(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    service.open_dashboard(password)
    service.close_dashboard()
    assert service.is_monitoring()


def test_08_exit_requires_auth(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    assert service.request_exit("nope") is False
    assert service.request_exit(password) is True
    assert "AGENT_EXIT" in types(service)


def test_09_activity_without_recording_input(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    sample = service.activity.sample()
    assert set(sample.__dataclass_fields__) == {"sampled_at", "idle_seconds"}


def test_10_and_11_inactive_then_active(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password, logged_in=True)
    service.start()
    platform.idle = 0
    service.tick()
    clock.advance(30)
    platform.idle = 30
    service.tick()
    assert service.engine.state.activity_status() == "INACTIVE"
    platform.idle = 0
    service.tick()
    assert service.engine.state.activity_status() == "ACTIVE"


def test_12_and_13_lock_unlock(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password, logged_in=True)
    service.start()
    platform.emit_session("LOCKED")
    assert service.engine.state.employee_status() == "LOCKED"
    platform.emit_session("UNLOCKED")
    assert "UNLOCKED" in types(service)


def test_14_login_logout_distinct_from_startup(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password, logged_in=False)
    service.start()
    assert types(service) == ["STARTUP"]
    platform.emit_session("LOGIN")
    platform.emit_session("LOGOUT")
    assert types(service)[0] == "STARTUP"
    assert "LOGIN" in types(service)
    assert "LOGOUT" in types(service)


def test_15_shutdown_recorded(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    platform.emit_power("SHUTDOWN")
    assert "SHUTDOWN" in types(service)


def test_16_and_17_auto_start_reconnects_after_reboot(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password, logged_in=True)
    service.start()
    service.tick()
    platform.emit_power("SHUTDOWN")
    service.state_store.save(service.engine.persist_record())
    platform.reboot("boot-2")
    clock.advance(60)
    restarted = build_service(tmp_path, clock, platform, password, logged_in=False)
    restarted.start()
    assert restarted.platform.startup_enabled()
    assert "STARTUP" in types(restarted)
    platform.emit_session("LOGIN")
    restarted.tick()
    assert "ONLINE" in types(restarted)


def test_18_unexpected_offline_without_invented_shutdown(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password, logged_in=True)
    clock.set(dt(8, 30, 0))
    service.start()
    service.tick()
    hb = service.engine.state.last_server_communication
    service.state_store.save(service.engine.persist_record())
    platform.reboot("boot-x")
    clock.set(dt(8, 47, 21))
    restarted = build_service(tmp_path, clock, platform, password, logged_in=False)
    restarted.start()
    unexpected = [e for e in restarted.engine.events if e.event_type.value == "UNEXPECTED_OFFLINE"]
    assert unexpected and unexpected[0].timestamp == hb
    assert "SHUTDOWN" not in types(restarted)


def test_19_fastapi_heartbeat_contract():
    from app.heartbeat.protocol import HEARTBEAT_PATH

    assert HEARTBEAT_PATH == "/api/v1/agent/heartbeat"


def test_windows_session_message_mapping():
    plat = WindowsPlatform()
    assert plat.handle_session_notification(WTS_SESSION_LOCK) == "LOCKED"
    assert plat.handle_session_notification(WTS_SESSION_UNLOCK) == "UNLOCKED"
    assert plat.handle_session_notification(WTS_SESSION_LOGON) == "LOGIN"
    assert plat.handle_session_notification(WTS_SESSION_LOGOFF) == "LOGOUT"
    assert plat.handle_end_session(0) == "SHUTDOWN"
    assert plat.handle_end_session(0x80000000) == "LOGOUT"
