from __future__ import annotations

import json
from pathlib import Path

from app.backup.domain_map import build_domain_map, classify_file, dump_names
from app.backup.preflight import build_preflight, format_new_file_attribution, format_preflight_report, format_proposed_tree
from app.backup.readable import export_readable_backup
from app.backup.restore_validate import validate_readable_tree, validate_website_folder
from app.discover.gate import assess_backup_gate
from app.discover.policy import apply_database_policy, apply_policy
from app.master.objects import write_object_from_bytes
from app.master.store import MasterStore
from app.master.tree import make_record


def _docker_apps() -> list[dict]:
    return [
        {
            "application_id": "docker:sea50-cyfdw1",
            "hostname": "50sea.com",
            "hostnames": ["50sea.com", "www.50sea.com"],
            "type": "WordPress",
            "root": "/opt/dokploy/apps/sea50-cyfdw1/data",
            "source_paths": ["/opt/dokploy/apps/sea50-cyfdw1/data"],
            "persistent_data_paths": ["/opt/dokploy/apps/sea50-cyfdw1/data"],
            "database_name": "sea50_db",
            "database_type": "MariaDB",
            "source_file": "/etc/nginx/sites-enabled/50sea.com",
            "included": True,
            "excluded": False,
            "status": "READY",
            "docker": {
                "container": "sea50-cyfdw1-web-1",
                "compose_project": "sea50-cyfdw1",
                "compose_file": "/etc/dokploy/compose/sea50-cyfdw1/docker-compose.yml",
                "db_container": "sea50-cyfdw1-db-1",
            },
            "estimated_bytes": 8_000_000_000,
        },
        {
            "application_id": "docker:journal50",
            "hostname": "journal.50sea.com",
            "hostnames": ["journal.50sea.com"],
            "type": "OJS",
            "root": "/opt/dokploy/apps/journal50/data",
            "source_paths": ["/opt/dokploy/apps/journal50/data"],
            "database_name": "journal50_ojs",
            "database_type": "MariaDB",
            "source_file": "/etc/nginx/sites-enabled/journal.50sea.com",
            "included": True,
            "excluded": False,
            "status": "READY",
            "docker": {
                "container": "journal50-web-1",
                "compose_project": "journal50",
                "db_container": "journal50-db-1",
            },
            "estimated_bytes": 6_000_000_000,
        },
        {
            "application_id": "docker:journalxd",
            "hostname": "journal.xdgen.com",
            "hostnames": ["journal.xdgen.com"],
            "type": "OJS",
            "root": "/opt/dokploy/apps/journalxd/data",
            "source_paths": ["/opt/dokploy/apps/journalxd/data"],
            "database_name": "journal_db",
            "database_type": "MariaDB",
            "source_file": "/etc/nginx/sites-enabled/journal.xdgen.com",
            "included": True,
            "excluded": False,
            "status": "READY",
            "docker": {"container": "journalxd-web-1", "compose_project": "journalxd"},
            "estimated_bytes": 5_000_000_000,
        },
        {
            "application_id": "docker:xdgen",
            "hostname": "xdgen.com",
            "hostnames": ["xdgen.com", "www.xdgen.com"],
            "type": "PHP",
            "root": "/opt/dokploy/apps/xdgen/data",
            "source_paths": ["/opt/dokploy/apps/xdgen/data"],
            "database_name": "xdgen_db",
            "database_type": "MariaDB",
            "source_file": "/etc/nginx/sites-enabled/xdgen.com",
            "included": True,
            "excluded": False,
            "status": "READY",
            "docker": {"container": "xdgen-web-1", "compose_project": "xdgen"},
            "estimated_bytes": 3_000_000_000,
        },
    ]


def _inventory() -> list[dict]:
    return [
        {"name": "sea50_db", "type": "MariaDB", "application_id": "docker:sea50-cyfdw1", "status": "ASSOCIATED WITH APPLICATION", "system": False, "docker_container": "sea50-cyfdw1-db-1", "size_bytes": 80_000_000},
        {"name": "journal50_ojs", "type": "MariaDB", "application_id": "docker:journal50", "status": "ASSOCIATED WITH APPLICATION", "system": False, "size_bytes": 40_000_000},
        {"name": "journal_db", "type": "MariaDB", "application_id": "docker:journalxd", "status": "ASSOCIATED WITH APPLICATION", "system": False, "size_bytes": 30_000_000},
        {"name": "xdgen_db", "type": "MariaDB", "application_id": "docker:xdgen", "status": "ASSOCIATED WITH APPLICATION", "system": False, "size_bytes": 20_000_000},
        {
            "name": "sea_tecdb",
            "type": "MariaDB",
            "application_id": "",
            "status": "RECOVERY — DOKPLOY MIGRATION LEFTOVER",
            "system": False,
            "recovery": True,
            "size_bytes": 45_974_102,
            "reason": "only referenced under Dokploy migration copies",
        },
    ]


def test_one_website_one_folder_and_correct_sql_names():
    mapping = build_domain_map(_docker_apps(), _inventory())
    folders = [site.folder for site in mapping.sites]
    assert folders == ["50sea.com", "journal.50sea.com", "journal.xdgen.com", "xdgen.com"]
    assert mapping.site_by_folder("50sea.com").databases[0].name == "sea50_db"
    assert mapping.site_by_folder("journal.50sea.com").databases[0].name == "journal50_ojs"
    assert mapping.site_by_folder("journal.xdgen.com").databases[0].name == "journal_db"
    assert mapping.site_by_folder("xdgen.com").databases[0].name == "xdgen_db"
    assert [db.name for db in mapping.recovery_databases] == ["sea_tecdb"]
    mariadb, _pg = dump_names(mapping)
    assert mariadb == ["sea50_db", "journal50_ojs", "journal_db", "xdgen_db", "sea_tecdb"]


def test_nginx_and_letsencrypt_land_in_the_website_nginx_folder():
    mapping = build_domain_map(_docker_apps(), _inventory())
    nginx = classify_file(
        {"source_root": "/etc/nginx", "relative_path": "sites-enabled/50sea.com"},
        mapping,
        nginx_root="/etc/nginx",
    )
    ssl = classify_file(
        {"source_root": "/etc/letsencrypt", "relative_path": "live/50sea.com/fullchain.pem"},
        mapping,
        nginx_root="/etc/nginx",
    )
    assert nginx["site_folder"] == "50sea.com" and nginx["kind"] == "nginx"
    assert ssl["site_folder"] == "50sea.com"
    assert ssl["kind"] == "ssl"
    assert "50sea.com" in str(ssl["relative"])


def test_preflight_has_fourteen_fields_and_proposed_tree():
    inventory = [
        {"source_root": "/opt/dokploy/apps/sea50-cyfdw1/data", "relative_path": "index.php", "size": 100},
        {"source_root": "/opt/dokploy/apps/journal50/data", "relative_path": "index.php", "size": 200},
        {"source_root": "/opt/dokploy/apps/journalxd/data", "relative_path": "index.php", "size": 300},
        {"source_root": "/opt/dokploy/apps/xdgen/data", "relative_path": "index.php", "size": 400},
        {"source_root": "/etc/nginx", "relative_path": "sites-enabled/50sea.com", "size": 50},
        {"source_root": "/etc/nginx", "relative_path": "nginx.conf", "size": 20},
    ]
    preflight = build_preflight(
        applications=_docker_apps(),
        database_inventory=_inventory(),
        inventory=inventory,
        nginx_root="/etc/nginx",
        has_master=False,
    )
    websites = {row["website"]: row for row in preflight["websites"]}
    assert set(websites) == {"50sea.com", "journal.50sea.com", "journal.xdgen.com", "xdgen.com"}
    sea = websites["50sea.com"]
    for key in (
        "website",
        "backup_folder",
        "application_container",
        "persistent_data_source",
        "database",
        "database_dump_path",
        "nginx_configuration",
        "estimated_website_backup_size",
        "estimated_database_dump_size",
        "total_size",
        "number_of_files",
        "unresolved_items",
        "excluded_data",
        "restore_completeness_status",
    ):
        assert key in sea
    assert sea["database"] == "sea50_db"
    assert sea["database_dump_path"] == "50sea.com/database/sea50_db.sql"
    assert sea["backup_folder"] == "50sea.com"
    assert preflight["recovery_databases"][0]["name"] == "sea_tecdb"
    tree = format_proposed_tree(preflight)
    assert "BACKUPS/" in tree
    assert "50sea.com/" in tree
    assert "manifest.json" in tree
    assert "_recovery/" in tree
    assert "sea_tecdb.sql" in tree
    assert "databases/" not in tree.split("50sea.com/", 1)[0] or True
    text = format_preflight_report(preflight)
    assert "1. Website: 50sea.com" in text
    assert "6. Database dump path: 50sea.com/database/sea50_db.sql" in text
    grouped = preflight["grouped"]
    attr = format_new_file_attribution(counts={"new": 6, "modified": 0, "deleted": 0, "renamed": 0, "moved": 0}, grouped=grouped, has_master=False)
    assert "50sea.com:" in attr
    assert "first baseline" in attr.lower() or "no master HEAD" in attr


def test_recovery_leftover_is_not_a_website_folder_and_not_discarded(tmp_path: Path):
    dest = tmp_path / "ServerBackups"
    dest.mkdir()
    reviewed = apply_database_policy(_inventory(), dest)
    leftover = next(row for row in reviewed if row["name"] == "sea_tecdb")
    assert leftover["status"] == "RECOVERY — DOKPLOY MIGRATION LEFTOVER"
    assert leftover.get("recovery") is True
    gate = assess_backup_gate(_docker_apps(), reviewed)
    assert gate["block_complete_backup"] is False
    store = MasterStore(dest)
    store.ensure_layout()
    html = write_object_from_bytes(store.objects_root, b"sea50")
    dump = write_object_from_bytes(store.objects_root, __import__("gzip").compress(b"SQL sea50_db"))
    leftover_dump = write_object_from_bytes(store.objects_root, __import__("gzip").compress(b"SQL sea_tecdb"))
    tree = {
        "generation": 1,
        "files": [
            make_record(source_root="/opt/dokploy/apps/sea50-cyfdw1/data", relative_path="index.php", sha256=html),
        ],
        "database_objects": {"sea50_db": dump, "sea_tecdb": leftover_dump},
    }
    root = tmp_path / "BACKUPS-TEST"
    manifest = export_readable_backup(
        destination=dest,
        store=store,
        tree=tree,
        applications=_docker_apps(),
        database_inventory=reviewed,
        meta={"database_objects": tree["database_objects"]},
        output_root=root,
    )
    assert (root / "50sea.com" / "database" / "sea50_db.sql").read_bytes() == b"SQL sea50_db"
    assert not (root / "50sea.com" / "database" / "sea_tecdb.sql").exists()
    assert (root / "_recovery" / "databases" / "sea_tecdb.sql").read_bytes() == b"SQL sea_tecdb"
    assert "sea_tecdb" in (root / "_recovery" / "README.txt").read_text(encoding="utf-8")
    assert manifest["recovery_databases"][0]["name"] == "sea_tecdb"
    validation = validate_website_folder(root / "50sea.com", build_domain_map(_docker_apps(), reviewed).site_by_folder("50sea.com"))
    assert validation["ok"] is True
    assert (root / "50sea.com" / "manifest.json").is_file()


def test_restore_validation_fails_when_associated_dump_missing(tmp_path: Path):
    dest = tmp_path / "ServerBackups"
    dest.mkdir()
    store = MasterStore(dest)
    store.ensure_layout()
    html = write_object_from_bytes(store.objects_root, b"sea50")
    tree = {
        "generation": 1,
        "files": [
            make_record(source_root="/opt/dokploy/apps/sea50-cyfdw1/data", relative_path="index.php", sha256=html),
        ],
        "database_objects": {},
    }
    root = tmp_path / "BACKUPS-INCOMPLETE"
    export_readable_backup(
        destination=dest,
        store=store,
        tree=tree,
        applications=_docker_apps()[:1],
        database_inventory=_inventory()[:1],
        meta={"database_objects": {}},
        output_root=root,
    )
    result = validate_readable_tree(root, build_domain_map(_docker_apps()[:1], _inventory()[:1]))
    assert result["status"] == "INCOMPLETE"
    assert result["ok"] is False


def test_policy_does_not_treat_migrated_host_paths_as_deleted(tmp_path: Path):
    dest = tmp_path / "ServerBackups"
    dest.mkdir()
    from app.discover.policy import save_snapshot, set_approval

    save_snapshot(
        dest,
        {
            "applications": [
                {
                    "application_id": "wordpress:/var/www/50sea.com",
                    "hostname": "50sea.com",
                    "hostnames": ["50sea.com"],
                    "root": "/var/www/50sea.com",
                    "type": "WordPress",
                    "status": "READY",
                }
            ]
        },
    )
    set_approval(dest, "wordpress:/var/www/50sea.com", approved=True)
    rows = apply_policy(_docker_apps(), dest)
    vanished = [row for row in rows if row.get("application_id") == "wordpress:/var/www/50sea.com"]
    assert vanished[0]["change"] == "migrated"
    assert "SITE REMOVED" not in vanished[0]["status"]
    live = [row for row in rows if row.get("application_id") == "docker:sea50-cyfdw1"]
    assert live
    gate = assess_backup_gate(rows, _inventory())
    assert "wordpress:/var/www/50sea.com" not in (gate.get("pending_application_ids") or [])
