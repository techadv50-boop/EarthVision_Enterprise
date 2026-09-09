from app.gui.icons import tray_color
from app.status.events import CONN_CONNECTED
from tests.conftest import build_service


def test_tray_indicator_states(tmp_path, clock, platform, password):
    from app.heartbeat.client import FakeHeartbeat

    service = build_service(tmp_path, clock, platform, password, logged_in=True)
    service.start()
    assert service.engine.state.tray_indicator() == "yellow"
    service.tick()
    assert service.engine.state.connection == CONN_CONNECTED
    assert service.engine.state.tray_indicator() == "green"
    snapshot = service.status_file.read()
    assert snapshot is not None
    assert snapshot["employee_id"] == "12"
    assert snapshot["device_id"] == "EMP12-PC"
    assert snapshot["connection_status"]
    assert snapshot["activity_status"]
    assert "password" not in str(snapshot).lower()


def test_tray_colors_match_status():
    assert tray_color("green")[1] > 100
    assert tray_color("yellow")[0] > 150
    assert tray_color("red")[0] > 150
    assert tray_color("warning")[0] > 150
