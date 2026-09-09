from app.config.paths import launch_command
from tests.conftest import build_service


def test_startup_registration_uses_background_flag(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    assert platform.startup_enabled()
    command = platform.startup_command()
    assert command is not None
    assert "--background" in command
    assert " --background" in launch_command(background=True)


def test_startup_failure_is_logged(tmp_path, clock, platform, password):
    platform.fail_startup("Access denied")
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    assert service.engine.state.config_error == "Access denied"
    log_text = service.paths.log_file.read_text(encoding="utf-8")
    assert "Failed to register Windows startup" in log_text
    assert service.engine.state.tray_indicator() == "warning"


def test_background_start_does_not_open_dashboard(tmp_path, clock, platform, password):
    service = build_service(tmp_path, clock, platform, password)
    service.start()
    assert service.access.dashboard_open is False
    assert service.is_monitoring() is True
