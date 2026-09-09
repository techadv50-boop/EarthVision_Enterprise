from tests.conftest import build_service
from tests.helpers import types


def test_exit_requires_authentication(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    assert service.request_exit("wrong") is False
    assert service.is_monitoring() is True
    assert "AGENT_EXIT" not in types(service)


def test_authenticated_exit_records_event_and_stops(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    assert service.request_exit(password) is True
    assert service.is_monitoring() is False
    assert "AGENT_EXIT" in types(service)
    assert service.events()[-1].event_type.value == "AGENT_EXIT"
