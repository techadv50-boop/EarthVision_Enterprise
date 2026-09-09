from tests.conftest import build_service


def test_dashboard_requires_password_every_open(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    assert service.open_dashboard("wrong") is False
    assert service.access.dashboard_open is False
    assert service.open_dashboard(password) is True
    assert service.access.dashboard_open is True
    service.close_dashboard()
    assert service.access.dashboard_open is False
    assert service.open_dashboard(password) is True
    service.close_dashboard()
    assert service.open_dashboard("wrong") is False


def test_closing_dashboard_does_not_stop_monitoring(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    assert service.open_dashboard(password)
    service.close_dashboard()
    assert service.is_monitoring() is True
    platform.idle = 0
    service.tick()
    assert service.engine.state.monitoring is True
