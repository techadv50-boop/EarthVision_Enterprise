from pathlib import Path

from app.backup.retention import apply_retention, list_successful_backups
from tests.helpers import write_success_backup


def _five(root: Path) -> list[str]:
    ids = [
        "2026-09-01_010000",
        "2026-09-02_010000",
        "2026-09-03_010000",
        "2026-09-04_010000",
        "2026-09-05_010000",
    ]
    for backup_id in ids:
        write_success_backup(root, backup_id)
    return ids


def test_sixth_success_removes_oldest(tmp_path: Path):
    root = tmp_path / "ServerBackups"
    ids = _five(root)
    write_success_backup(root, "2026-09-06_010000")
    removed = apply_retention(root, keep=5)
    remaining = [p.name for p in list_successful_backups(root)]
    assert ids[0] not in remaining
    assert remaining == ids[1:] + ["2026-09-06_010000"]
    assert removed[0].name == ids[0]


def test_failed_sixth_preserves_all_five(tmp_path: Path):
    root = tmp_path / "ServerBackups"
    ids = _five(root)
    incomplete = root / ".incomplete_2026-09-06_010000"
    incomplete.mkdir()
    (incomplete / "server-backup.tar.gz").write_bytes(b"partial")
    # Failed run must not call retention. Simulate cleanup of incomplete only.
    import shutil

    shutil.rmtree(incomplete)
    remaining = [p.name for p in list_successful_backups(root)]
    assert remaining == ids
    assert not incomplete.exists()


def test_incomplete_and_failed_do_not_count(tmp_path: Path):
    root = tmp_path / "ServerBackups"
    write_success_backup(root, "2026-09-01_010000")
    failed = root / "2026-09-02_010000"
    failed.mkdir()
    (failed / "backup-info.json").write_text('{"status": "FAILED"}', encoding="utf-8")
    (root / ".incomplete_2026-09-03_010000").mkdir()
    assert [p.name for p in list_successful_backups(root)] == ["2026-09-01_010000"]
