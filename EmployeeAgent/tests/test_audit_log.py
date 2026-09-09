from tests.conftest import build_service
from tests.helpers import types


def test_audit_log_contains_required_columns(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password, logged_in=True)
    service.start()
    platform.emit_session("LOCKED")
    platform.emit_session("UNLOCKED")
    rows = [event.as_row() for event in service.events()]
    assert rows
    for row in rows:
        assert {"time", "employee", "device", "event"} <= set(row)
        assert row["employee"] == "12"
        assert row["device"] == "EMP12-PC"
    events = {row["event"] for row in rows}
    assert "STARTUP" in events
    assert "LOCKED" in events
    assert "UNLOCKED" in events


def test_audit_persists_across_restart(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    service.tick()
    first = [e.event_type.value for e in service.events()]
    restarted = build_service(tmp_path, clock, platform, password)
    restarted.start()
    stored = [e.event_type.value for e in restarted.events()]
    for item in first:
        assert item in stored
