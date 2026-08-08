"""Isolation from the legacy app-data repository."""

from pathlib import Path

from webcrawler.auth.manager import DEFAULT_PASSWORD, DEFAULT_USERNAME, AuthManager
from webcrawler.db.database import Database
from webcrawler.launch import prepare_launch_session
from webcrawler.queue.manager import QueueManager
from webcrawler.settings.manager import (
    APP_DATA_FOLDER,
    LEGACY_APP_DATA_FOLDER,
    SettingsManager,
    app_data_dir,
    legacy_app_data_dir,
)


def test_app_data_folder_is_not_legacy_name():
    assert APP_DATA_FOLDER != LEGACY_APP_DATA_FOLDER
    assert APP_DATA_FOLDER.endswith("_v2")


def test_new_store_ignores_legacy_repository(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    legacy = tmp_path / LEGACY_APP_DATA_FOLDER
    legacy.mkdir(parents=True)
    # Poison the old repository — must never be opened by this build.
    (legacy / "settings.json").write_text(
        '{"last_urls": "https://legacy-only.example"}', encoding="utf-8"
    )
    legacy_db = Database(legacy / "crawler.db")
    AuthManager(legacy_db).change_password(
        DEFAULT_USERNAME,
        DEFAULT_PASSWORD,
        "LegacyPass99",
        "LegacyPass99",
        require_current=True,
    )
    QueueManager(legacy_db).enqueue_many(
        ["https://legacy-only.example"], str(tmp_path / "legacy-out")
    )

    # This build's data dir under the same config root.
    data = app_data_dir()
    assert data.name == APP_DATA_FOLDER
    assert data != legacy
    assert legacy_app_data_dir() == legacy

    info = prepare_launch_session()
    assert info["isolated"] is True
    assert info["imported_legacy"] is False
    assert info["legacy_present"] is True
    assert Path(info["data_dir"]) == data

    # Fresh auth DB in v2 folder — default admin/admin, not legacy password.
    auth = AuthManager(Database())
    assert auth.authenticate(DEFAULT_USERNAME, "LegacyPass99").ok is False
    ok = auth.authenticate(DEFAULT_USERNAME, DEFAULT_PASSWORD)
    assert ok.ok is True

    settings = SettingsManager()
    assert "legacy-only.example" not in (settings.settings.last_urls or "")
    assert QueueManager(Database()).count_unfinished() == 0
