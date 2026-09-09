from tests.conftest import build_service
from tests.helpers import types


def test_lock_and_unlock(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password, logged_in=True)
    service.start()
    service.tick()
    platform.emit_session("LOCKED")
    assert service.engine.state.activity_status() == "LOCKED"
    assert service.engine.state.employee_status() == "LOCKED"
    assert "LOCKED" in types(service)
    platform.idle = 0
    platform.emit_session("UNLOCKED")
    assert "UNLOCKED" in types(service)
    assert service.engine.state.activity_status() == "ACTIVE"
    assert service.engine.state.employee_status() == "ACTIVE"


def test_login_and_logout_are_distinct_from_startup(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password, logged_in=False)
    service.start()
    assert "STARTUP" in types(service)
    assert "LOGIN" not in types(service)
    platform.emit_session("LOGIN")
    assert types(service).index("STARTUP") < types(service).index("LOGIN")
    platform.emit_session("LOGOUT")
    assert "LOGOUT" in types(service)
    assert service.engine.state.activity_status() == "LOGGED_OUT"
    assert service.engine.state.employee_status() == "LOGGED_OUT"


def test_locked_does_not_emit_inactive(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password, logged_in=True)
    service.start()
    platform.emit_session("LOCKED")
    platform.idle = 90
    service.tick()
    assert "INACTIVE" not in types(service)
    assert service.engine.state.employee_status() == "LOCKED"
