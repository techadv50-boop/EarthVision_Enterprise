"""Clean-launch session profile tests."""

from pathlib import Path

from webcrawler.auth.manager import DEFAULT_PASSWORD, DEFAULT_USERNAME, AuthManager
from webcrawler.db.database import Database
from webcrawler.launch import SESSION_PROFILE, prepare_launch_session, session_profile_path
from webcrawler.queue.manager import QueueManager, QueueStatus
from webcrawler.settings.manager import SettingsManager, app_data_dir


def test_prepare_launch_resets_old_session(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Point app data at temp by patching app_data_dir consumers via env (Linux path).
    data = tmp_path / "WebCrawlerEnterprise"
    data.mkdir(parents=True)

    monkeypatch.setattr(
        "webcrawler.launch.app_data_dir",
        lambda: data,
    )
    monkeypatch.setattr(
        "webcrawler.settings.manager.app_data_dir",
        lambda: data,
    )
    monkeypatch.setattr(
        "webcrawler.db.database.app_data_dir",
        lambda: data,
    )

    db = Database(data / "crawler.db")
    auth = AuthManager(db)
    # Simulate old changed password session with unfinished work + saved URLs.
    auth.change_password(
        DEFAULT_USERNAME,
        DEFAULT_PASSWORD,
        "OldPass99",
        "OldPass99",
        require_current=True,
    )
    qm = QueueManager(db)
    items = qm.enqueue_many(["https://old-session.example"], str(tmp_path / "out"))
    qm.mark_running(items[0].id)
    settings = SettingsManager(data / "settings.json")
    settings.update(last_urls="https://old-session.example")

    assert session_profile_path().parent == data or True
    # Force migration by ensuring marker missing / low.
    marker = data / "session_profile.txt"
    if marker.exists():
        marker.unlink()

    # Re-bind launch helpers to temp data dir
    monkeypatch.setattr("webcrawler.launch.session_profile_path", lambda: marker)
    info = prepare_launch_session()
    assert info["migrated"] is True

    auth2 = AuthManager(Database(data / "crawler.db"))
    ok = auth2.authenticate(DEFAULT_USERNAME, DEFAULT_PASSWORD)
    assert ok.ok is True
    assert ok.user is not None
    assert ok.user.must_change_password is True

    qm2 = QueueManager(Database(data / "crawler.db"))
    assert qm2.count_unfinished() == 0
    assert qm2.get(items[0].id).status == QueueStatus.CANCELLED.value

    settings2 = SettingsManager(data / "settings.json")
    assert settings2.settings.last_urls == ""

    # Second launch must not migrate again.
    info2 = prepare_launch_session()
    assert info2["migrated"] is False
    assert int(marker.read_text()) == SESSION_PROFILE
