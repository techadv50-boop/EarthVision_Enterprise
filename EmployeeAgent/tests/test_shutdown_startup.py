from tests.conftest import build_service
from tests.helpers import dt, types
from app.status.offline import compute_offline_periods, format_duration


def test_shutdown_then_startup_timeline(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password, logged_in=True)
    clock.set(dt(8, 29, 55))
    platform.idle = 0
    service.start()
    service.tick()
    assert service.engine.state.employee_status() == "ACTIVE"

    clock.set(dt(8, 30, 10))
    platform.emit_power("SHUTDOWN")
    assert types(service)[-2:] == ["SHUTDOWN", "OFFLINE"]
    previous = service.engine.persist_record()
    service.state_store.save(previous)

    platform.reboot("boot-2")
    clock.set(dt(8, 47, 21))
    restarted = build_service(tmp_path, clock, platform, password, logged_in=False)
    restarted.start()
    assert "STARTUP" in types(restarted)
    startup_at = [e for e in restarted.engine.events if e.event_type.value == "STARTUP"][0].timestamp
    assert startup_at == dt(8, 47, 21)

    clock.set(dt(8, 47, 35))
    platform.emit_session("LOGIN")
    clock.set(dt(8, 47, 36))
    restarted.tick()
    clock.set(dt(8, 47, 40))
    platform.idle = 0
    restarted.tick()

    assert types(restarted)[0:3] == ["STARTUP", "LOGIN", "ONLINE"] or "LOGIN" in types(restarted)
    combined = service.engine.events + restarted.engine.events
    periods = compute_offline_periods(combined)
    assert periods
    assert format_duration(periods[0].duration) == "17 minutes 11 seconds"
    assert periods[0].kind in {"SHUTDOWN", "OFFLINE"}


def test_restart_event(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    platform.emit_power("RESTART")
    assert "RESTART" in types(service)
    assert "OFFLINE" in types(service)
