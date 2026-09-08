import sys
from pathlib import Path

from app.master.restore import select_tree_files, write_restore_pack
from app.master.store import MasterStore
from app.restore.restore_engine import CONFIRMATION_PHRASE, RestoreEngine, RestoreError
from tests.helpers import LocalMasterSSH, make_config, master_config, seed_remote_tree


def test_restore_requires_confirmation(tmp_path):
    cfg = make_config(tmp_path)
    engine = RestoreEngine(cfg)
    try:
        engine.restore(tmp_path, confirmation="yes", action="restore-files")
        assert False, "must require RESTORE"
    except RestoreError as exc:
        assert CONFIRMATION_PHRASE in str(exc)


def test_restore_engine_passes_ssh_client_through(tmp_path):
    cfg = make_config(tmp_path)
    ssh = LocalMasterSSH(tmp_path)
    engine = RestoreEngine(cfg, ssh=ssh)
    assert engine.ssh is ssh


def test_master_restore_pack_roundtrip(tmp_path, monkeypatch):
    from app.engine.backup_engine import BackupEngine

    ubuntu = Path(__file__).resolve().parents[1] / "scripts" / "ubuntu"
    if str(ubuntu) not in sys.path:
        sys.path.insert(0, str(ubuntu))
    import restore_master

    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
    store = MasterStore(cfg.backup_destination)
    tree = store.load_tree()
    records = select_tree_files(tree, kind="restore-files", target_path=remote["xdgen.com"])
    pack = tmp_path / "restore.sb01"
    write_restore_pack(store, records, pack)
    target = Path(remote["xdgen.com"]) / "index.html"
    original = target.read_text(encoding="utf-8")
    target.write_text("mutated\n", encoding="utf-8")
    monkeypatch.setattr(restore_master, "safety_root", lambda: tmp_path / "safety")
    result = restore_master.apply_pack(
        {"pack_path": str(pack), "create_safety_copy": True, "reload_nginx": False}
    )
    assert result["ok"] is True
    assert result["nginx_restarted"] is False
    assert target.read_text(encoding="utf-8") == original


def test_historical_generation_pack_uses_requested_tree(tmp_path):
    from app.engine.backup_engine import BackupEngine

    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
    Path(remote["xdgen.com"], "index.html").write_text("generation-2\n", encoding="utf-8")
    BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
    store = MasterStore(cfg.backup_destination)
    assert store.head_generation() == 2
    tree1 = store.load_tree(1)
    records = select_tree_files(tree1, kind="restore-files", target_path=remote["xdgen.com"])
    assert any(item.get("relative_path") == "index.html" for item in records)
    pack = tmp_path / "gen1.sb01"
    write_restore_pack(store, records, pack)
    assert pack.stat().st_size > 0
