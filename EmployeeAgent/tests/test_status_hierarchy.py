from app.status.hierarchy import tray_indicator, workstation_status
from app.status.events import CONN_CONNECTED, CONN_CONNECTING, CONN_UNAVAILABLE


def test_hierarchy_active():
    assert (
        workstation_status(lifecycle=None, presence="ACTIVE", connection=CONN_CONNECTED)
        == "ACTIVE"
    )


def test_hierarchy_inactive_is_not_offline():
    assert (
        workstation_status(lifecycle=None, presence="INACTIVE", connection=CONN_CONNECTED)
        == "INACTIVE"
    )
    assert (
        workstation_status(lifecycle=None, presence="ACTIVE", connection=CONN_UNAVAILABLE)
        == "OFFLINE"
    )


def test_hierarchy_lock_and_logout_precede_activity():
    assert (
        workstation_status(lifecycle=None, presence="LOCKED", connection=CONN_CONNECTED)
        == "LOCKED"
    )
    assert (
        workstation_status(lifecycle=None, presence="LOGGED_OUT", connection=CONN_CONNECTED)
        == "LOGGED_OUT"
    )


def test_hierarchy_lifecycle():
    assert (
        workstation_status(lifecycle="SHUTDOWN", presence="ACTIVE", connection=CONN_UNAVAILABLE)
        == "SHUTDOWN"
    )
    assert (
        workstation_status(lifecycle="STARTUP", presence="LOGGED_OUT", connection=CONN_CONNECTING)
        == "STARTUP"
    )


def test_tray_colors():
    assert tray_indicator(connection=CONN_CONNECTED, config_error=None, monitoring=True) == "green"
    assert tray_indicator(connection=CONN_CONNECTING, config_error=None, monitoring=True) == "yellow"
    assert tray_indicator(connection=CONN_UNAVAILABLE, config_error=None, monitoring=True) == "red"
    assert tray_indicator(connection=CONN_CONNECTED, config_error="bad", monitoring=True) == "warning"
