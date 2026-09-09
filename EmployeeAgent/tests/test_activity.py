from tests.conftest import build_service
from tests.helpers import dt, types


def test_thirty_seconds_idle_becomes_inactive(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password, logged_in=True)
    platform.idle = 0
    service.start()
    service.tick()
    assert service.engine.state.activity_status() == "ACTIVE"
    clock.set(dt(8, 30, 25))
    platform.idle = 30
    service.tick()
    assert service.engine.state.activity_status() == "INACTIVE"
    assert "INACTIVE" in types(service)
    assert service.engine.state.employee_status() == "INACTIVE"


def test_activity_returns_to_active(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password, logged_in=True)
    service.start()
    platform.idle = 0
    service.tick()
    clock.advance(30)
    platform.idle = 30
    service.tick()
    assert service.engine.state.activity_status() == "INACTIVE"
    platform.idle = 1
    service.tick()
    assert service.engine.state.activity_status() == "ACTIVE"
    assert types(service).count("ACTIVE") >= 1
    assert types(service).count("INACTIVE") == 1


def test_activity_sample_has_no_input_content(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    sample = service.activity.sample()
    assert sample.allowed_fields() == ("sampled_at", "idle_seconds")
    assert not hasattr(sample, "keys")
    assert not hasattr(sample, "x")
    assert not hasattr(sample, "y")
    assert "key" not in sample.__dataclass_fields__
