from tests.conftest import build_service
from tests.helpers import dt, types
from app.status.events import EventType
from app.status.offline import compute_offline_periods


def test_unexpected_offline_uses_last_heartbeat_not_invented_shutdown(
    tmp_path, clock, platform, password
):
    service = build_service(tmp_path, clock, platform, password, logged_in=True)
    clock.set(dt(8, 29, 55))
    service.start()
    service.tick()
    last_heartbeat = service.engine.state.last_server_communication
    assert last_heartbeat is not None
    service.state_store.save(service.engine.persist_record())
    assert service.engine.persist_record().clean_power_off is False
    assert "SHUTDOWN" not in types(service)

    platform.reboot("boot-crash")
    clock.set(dt(8, 47, 21))
    restarted = build_service(tmp_path, clock, platform, password, logged_in=False)
    restarted.start()

    unexpected = [e for e in restarted.engine.events if e.event_type == EventType.UNEXPECTED_OFFLINE]
    assert unexpected, types(restarted)
    assert unexpected[0].timestamp == last_heartbeat
    assert unexpected[0].approximate is True
    assert "SHUTDOWN" not in types(restarted)
    startup = [e for e in restarted.engine.events if e.event_type == EventType.STARTUP][0]
    assert startup.timestamp == dt(8, 47, 21)
    assert startup.timestamp != unexpected[0].timestamp

    periods = compute_offline_periods(restarted.engine.events)
    assert periods
    assert periods[0].kind == "UNEXPECTED_OFFLINE"
    assert periods[0].approximate_start is True
    assert periods[0].start == last_heartbeat
    assert periods[0].end == dt(8, 47, 21)
