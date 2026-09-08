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


def test_sudoers_template_still_has_only_three_script_paths():
    text = Path(__file__).resolve().parents[1].joinpath("scripts/ubuntu/ubuntu-backup-setup.sh").read_text(encoding="utf-8")
    block = text.split('cat >"$TMP" <<EOF', 1)[1].split("EOF", 1)[0]
    assert "NOPASSWD: /usr/local/lib/serverbackup/prepare-backup.sh" in block
    assert "NOPASSWD: /usr/local/lib/serverbackup/restore-backup.sh" in block
    assert "NOPASSWD: /usr/local/lib/serverbackup/security-audit.sh" in block
    rules = [line for line in block.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    for line in rules:
        assert "NOPASSWD: ALL" not in line
    assert sum(line.count("NOPASSWD:") for line in rules) == 3


def test_setup_completed_roundtrip(tmp_path: Path):
    from app.config.store import load_config, save_config

    cfg = AppConfig(setup_completed=True, backup_destination=str(tmp_path))
    path = tmp_path / "config.json"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.setup_completed is True
