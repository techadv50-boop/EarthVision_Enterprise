from pathlib import Path

from app.config.schema import AppConfig
from app.utils.disk import backup_folder_for_drive, list_backup_drives, needs_setup


def test_backup_folder_for_windows_drive_letter():
    assert backup_folder_for_drive("G:\\") == "G:\\ServerBackups"
    assert backup_folder_for_drive("G:") == "G:\\ServerBackups"
    assert backup_folder_for_drive("G:\\ServerBackups").rstrip("\\").endswith("ServerBackups")


def test_backup_folder_for_drive_appends_serverbackups(tmp_path: Path):
    folder = backup_folder_for_drive(tmp_path)
    assert Path(folder).name == "ServerBackups"
    already = tmp_path / "ServerBackups"
    assert Path(backup_folder_for_drive(already)).name == "ServerBackups"


def test_needs_setup_until_user_completes(tmp_path: Path):
    cfg = AppConfig(setup_completed=False, backup_destination=str(tmp_path / "ServerBackups"))
    assert needs_setup(cfg) is True
    cfg.setup_completed = True
    assert needs_setup(cfg) is False


def test_list_backup_drives_returns_existing_roots():
    drives = list_backup_drives()
    assert drives
    assert all(item.exists for item in drives)
    assert all(item.path for item in drives)


def test_setup_completed_roundtrip(tmp_path: Path):
    from app.config.store import load_config, save_config

    cfg = AppConfig(setup_completed=True, backup_destination=str(tmp_path))
    path = tmp_path / "config.json"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.setup_completed is True
