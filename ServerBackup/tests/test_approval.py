from __future__ import annotations

from pathlib import Path

from app.discover.approval import (
    approve_selected_applications,
    format_application_approval_block,
    split_approval_applications,
)
from app.discover.gate import assess_backup_gate
from app.discover.policy import (
    apply_policy,
    approve_all_applications,
    save_snapshot,
    snapshot_application_row,
)
from app.engine.backup_engine import BackupEngine
from app.engine.status import collect_dashboard_status, format_discovery_count
from tests.helpers import LocalMasterSSH, make_config, master_config, seed_remote_tree


def live_shaped_apps() -> list[dict]:
    return [
        {
            "application_id": "wordpress:/var/www/50sea.com",
            "hostname": "50sea.com",
            "hostnames": ["50sea.com", "www.50sea.com"],
            "type": "WordPress",
            "root": "/var/www/50sea.com",
            "database_type": "MariaDB",
            "database_name": "sea_tecdb",
            "status": "NEW SITE DETECTED — REQUIRES APPROVAL",
            "included": False,
            "excluded": False,
            "ojs_files_dir": "",
        },
        {
            "application_id": "ojs:/var/www/journal.50sea.com",
            "hostname": "journal.50sea.com",
            "hostnames": ["journal.50sea.com"],
            "type": "OJS",
            "root": "/var/www/journal.50sea.com",
            "database_type": "MariaDB",
            "database_name": "journal50_ojs",
            "status": "NEW SITE DETECTED — REQUIRES APPROVAL",
            "included": False,
            "excluded": False,
            "ojs_files_dir": "/var/lib/ojs-journal50",
        },
        {
            "application_id": "ojs:/var/www/journal.xdgen.com",
            "hostname": "journal.xdgen.com",
            "hostnames": ["journal.xdgen.com"],
            "type": "OJS",
            "root": "/var/www/journal.xdgen.com",
            "database_type": "MariaDB",
            "database_name": "journal_db",
            "status": "NEW SITE DETECTED — REQUIRES APPROVAL",
            "included": False,
            "excluded": False,
            "ojs_files_dir": "/var/www/ojs-files",
        },
        {
            "application_id": "php:/var/www/xdgen.com",
            "hostname": "xdgen.com",
            "hostnames": ["xdgen.com", "www.xdgen.com"],
            "type": "PHP",
            "root": "/var/www/xdgen.com",
            "database_type": "MariaDB",
            "database_name": "xdgen_db",
            "status": "NEW SITE DETECTED — REQUIRES APPROVAL",
            "included": False,
            "excluded": False,
            "ojs_files_dir": "",
        },
        {
            "application_id": "other:/var/www/html",
            "hostname": "_",
            "hostnames": ["_"],
            "type": "Other",
            "root": "/var/www/html",
            "status": "EXCLUDED — UNUSED DEFAULT ROOT",
            "included": False,
            "excluded": True,
            "unused_default_root": True,
            "ojs_files_dir": "",
        },
    ]


def live_databases() -> list[dict]:
    mapping = {
        "sea_tecdb": "wordpress:/var/www/50sea.com",
        "journal50_ojs": "ojs:/var/www/journal.50sea.com",
        "journal_db": "ojs:/var/www/journal.xdgen.com",
        "xdgen_db": "php:/var/www/xdgen.com",
    }
    return [
        {
            "name": name,
            "type": "MariaDB",
            "status": "ASSOCIATED WITH APPLICATION",
            "application_id": ident,
            "system": False,
        }
        for name, ident in mapping.items()
    ]


def test_approval_block_lists_ojs_files_and_databases():
    blocks = {row["application_id"]: format_application_approval_block(row) for row in live_shaped_apps()}
    assert "50sea.com, www.50sea.com" in blocks["wordpress:/var/www/50sea.com"]
    assert "MariaDB sea_tecdb" in blocks["wordpress:/var/www/50sea.com"]
    assert "OJS files: /var/lib/ojs-journal50" in blocks["ojs:/var/www/journal.50sea.com"]
    assert "MariaDB journal50_ojs" in blocks["ojs:/var/www/journal.50sea.com"]
    assert "OJS files: /var/www/ojs-files" in blocks["ojs:/var/www/journal.xdgen.com"]
    assert "MariaDB journal_db" in blocks["ojs:/var/www/journal.xdgen.com"]
    assert "xdgen.com, www.xdgen.com" in blocks["php:/var/www/xdgen.com"]
    assert "MariaDB xdgen_db" in blocks["php:/var/www/xdgen.com"]
    assert "UNUSED DEFAULT ROOT" in blocks["other:/var/www/html"]


def test_split_keeps_html_in_excluded_not_pending():
    pending, approved, excluded = split_approval_applications(live_shaped_apps())
    assert [row["application_id"] for row in pending] == [
        "wordpress:/var/www/50sea.com",
        "ojs:/var/www/journal.50sea.com",
        "ojs:/var/www/journal.xdgen.com",
        "php:/var/www/xdgen.com",
    ]
    assert approved == []
    assert [row["application_id"] for row in excluded] == ["other:/var/www/html"]


def test_approve_all_skips_unused_default_without_override(tmp_path: Path):
    dest = tmp_path / "ServerBackups"
    dest.mkdir()
    apps = live_shaped_apps()
    approved = approve_all_applications(dest, apps)
    assert approved == [
        "wordpress:/var/www/50sea.com",
        "ojs:/var/www/journal.50sea.com",
        "ojs:/var/www/journal.xdgen.com",
        "php:/var/www/xdgen.com",
    ]
    assert "other:/var/www/html" not in approved
    after = apply_policy(apps, dest)
    pending, included, excluded = split_approval_applications(after)
    assert pending == []
    assert [row["application_id"] for row in included] == approved
    assert excluded[0]["application_id"] == "other:/var/www/html"
    assert excluded[0]["included"] is False
    gate = assess_backup_gate(after, live_databases())
    assert gate["applications_approved"] == 4
    assert gate["applications_excluded"] == 1
    assert gate["applications_pending"] == 0
    assert gate["databases_discovered"] == 4
    assert gate["databases_associated"] == 4
    assert gate["databases_unresolved"] == 0
    assert gate["block_complete_backup"] is False


def test_approve_selected_does_not_take_unchecked_or_html(tmp_path: Path):
    dest = tmp_path / "ServerBackups"
    dest.mkdir()
    apps = live_shaped_apps()
    approved = approve_selected_applications(
        dest,
        apps,
        ["wordpress:/var/www/50sea.com", "other:/var/www/html"],
    )
    assert approved == ["wordpress:/var/www/50sea.com"]
    after = apply_policy(apps, dest)
    pending, included, excluded = split_approval_applications(after)
    assert [row["application_id"] for row in included] == ["wordpress:/var/www/50sea.com"]
    assert len(pending) == 3
    assert excluded[0]["application_id"] == "other:/var/www/html"


def test_approve_all_override_can_include_unused_default(tmp_path: Path):
    dest = tmp_path / "ServerBackups"
    dest.mkdir()
    apps = live_shaped_apps()
    approved = approve_all_applications(dest, apps, include_unused_default=True)
    assert "other:/var/www/html" in approved
    assert len(approved) == 5


def test_apply_policy_clears_new_site_status_after_approval(tmp_path: Path):
    dest = tmp_path / "ServerBackups"
    dest.mkdir()
    apps = live_shaped_apps()
    approve_all_applications(dest, apps)
    after = apply_policy(apps, dest)
    wordpress = next(row for row in after if row["application_id"] == "wordpress:/var/www/50sea.com")
    assert wordpress["included"] is True
    assert wordpress["status"] == "READY"
    html = next(row for row in after if row["application_id"] == "other:/var/www/html")
    assert html["excluded"] is True
    assert html["included"] is False


def test_dashboard_shows_zero_approved_not_dash_then_four_after_approval(tmp_path: Path):
    cfg = make_config(tmp_path)
    dest = Path(cfg.backup_destination)
    dest.mkdir(parents=True, exist_ok=True)
    apps = apply_policy(live_shaped_apps(), dest)
    save_snapshot(dest, {"applications": [snapshot_application_row(row) for row in apps], "database_inventory": live_databases()})
    before = collect_dashboard_status(cfg)
    assert before["discovered_approved"] == 0
    assert before["discovered_review"] == 4
    assert format_discovery_count(before["discovered_approved"]) == "0"
    assert format_discovery_count(before["discovered_review"]) == "4"
    assert format_discovery_count(before["discovered_removed"], zero_as_dash=True) == "—"
    approve_all_applications(dest, apps)
    after_apps = apply_policy(live_shaped_apps(), dest)
    save_snapshot(
        dest,
        {"applications": [snapshot_application_row(row) for row in after_apps], "database_inventory": live_databases()},
    )
    after = collect_dashboard_status(cfg)
    assert after["discovered_approved"] == 4
    assert after["discovered_review"] == 0
    assert format_discovery_count(after["discovered_approved"]) == "4"
    assert format_discovery_count(after["discovered_review"]) == "0"
    assert format_discovery_count(after["discovered_removed"], zero_as_dash=True) == "—"


def test_snapshot_persists_ojs_files_dir(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    from app.discover.engine import discover_applications
    from app.discover.policy import load_snapshot

    result = discover_applications(cfg, ssh=LocalMasterSSH(tmp_path / "remote"), persist=True)
    journal = next(app for app in result["applications"] if "journal.50sea.com" in str(app.get("root")))
    assert journal.get("ojs_files_dir")
    snap = load_snapshot(cfg.backup_destination)
    saved = next(app for app in snap["applications"] if app.get("application_id") == journal.get("application_id"))
    assert saved.get("ojs_files_dir") == journal.get("ojs_files_dir")


def test_dry_run_after_approval_shows_pending_zero(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    ssh = LocalMasterSSH(tmp_path / "remote")
    from tests.helpers import enable_backup

    enable_backup(cfg, ssh)
    result = BackupEngine(cfg, ssh=ssh).dry_run()
    text = result["report_text"]
    assert "Applications pending: 0" in text
    assert "EXPECTED ACTION: FULL MASTER BASELINE" in text
    assert "dump-databases" not in ssh.calls
    assert "stream-objects" not in ssh.calls


def test_discover_finished_does_not_hide_approval_behind_report_dialog():
    source = Path(__file__).resolve().parents[1] / "app" / "gui" / "main_window.py"
    text = source.read_text(encoding="utf-8")
    finished = text.split("def _on_discover_finished", 1)[1].split("def _on_applications_approved", 1)[0]
    assert "QMessageBox.information" not in finished
    assert "self.discover_page.reload" in finished
    assert "stack.setCurrentWidget(self.discover_page)" in finished
    discover = text.split("def discover_server", 1)[1].split("def _on_discover_finished", 1)[0]
    assert "BackupEngine" not in discover
    assert ".run(" not in discover
    assert "REVIEW / APPROVE APPLICATIONS" in text
    dashboard = text.split("class DashboardPage", 1)[1].split("class MainWindow", 1)[0]
    assert 'str(status.get("discovered_approved") or "—")' not in dashboard
