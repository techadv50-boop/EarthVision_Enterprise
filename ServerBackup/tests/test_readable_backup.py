from __future__ import annotations

import json
from pathlib import Path

from app.backup.domain_map import (
    build_domain_map,
    classify_file,
    dump_names,
    sanitize_domain_folder,
)
from app.backup.readable import READABLE_DIR, export_readable_backup, readable_root
from app.engine.backup_engine import BackupEngine
from app.master.objects import write_object_from_bytes
from app.master.store import MasterStore
from app.master.tree import make_record
from tests.helpers import LocalMasterSSH, enable_backup, master_config, seed_remote_tree, write_success_backup


def _approved(app: dict, **extra) -> dict:
    row = dict(app)
    row.update(extra)
    row["included"] = True
    row["excluded"] = False
    row.setdefault("status", "READY")
    return row


def _apps() -> list[dict]:
    return [
        _approved(
            {
                "application_id": "ojs:/var/www/journal.50sea.com",
                "hostname": "journal.50sea.com",
                "hostnames": ["journal.50sea.com"],
                "type": "OJS",
                "root": "/var/www/journal.50sea.com",
                "ojs_files_dir": "/var/lib/ojs-journal50",
                "source_paths": ["/var/www/journal.50sea.com", "/var/lib/ojs-journal50"],
                "persistent_data_paths": ["/var/lib/ojs-journal50"],
                "database_name": "ojs50",
                "database_type": "MariaDB",
                "source_file": "/etc/nginx/sites-enabled/journal.50sea.com",
            }
        ),
        _approved(
            {
                "application_id": "wordpress:/var/www/50sea.com",
                "hostname": "50sea.com",
                "hostnames": ["50sea.com", "www.50sea.com"],
                "type": "WordPress",
                "root": "/var/www/50sea.com",
                "source_paths": ["/var/www/50sea.com"],
                "database_name": "sea_tedb",
                "database_type": "MariaDB",
                "source_file": "/etc/nginx/sites-enabled/50sea.com",
            }
        ),
        _approved(
            {
                "application_id": "static:/var/www/xdgen.com",
                "hostname": "xdgen.com",
                "hostnames": ["xdgen.com", "www.xdgen.com"],
                "type": "Static",
                "root": "/var/www/xdgen.com",
                "source_paths": ["/var/www/xdgen.com"],
            }
        ),
        _approved(
            {
                "application_id": "docker:citation",
                "hostname": "citation.xdgen.com",
                "hostnames": ["citation.xdgen.com"],
                "type": "Docker",
                "root": "",
                "source_paths": ["/opt/citation/data"],
                "persistent_data_paths": ["volume:citation_pgdata", "/opt/citation/data"],
                "database_name": "citation",
                "database_type": "PostgreSQL",
                "docker": {
                    "container": "citation_web",
                    "compose_project": "citation",
                    "compose_file": "/opt/citation/docker-compose.yml",
                    "service": "citation_web",
                },
            }
        ),
        {
            "application_id": "other:/var/www/html",
            "hostname": "_",
            "hostnames": ["_"],
            "type": "Other",
            "root": "/var/www/html",
            "source_paths": ["/var/www/html"],
            "included": False,
            "excluded": True,
            "unused_default_root": True,
            "status": "EXCLUDED — UNUSED DEFAULT ROOT",
        },
    ]


def _inventory() -> list[dict]:
    return [
        {"name": "ojs50", "type": "MariaDB", "application_id": "ojs:/var/www/journal.50sea.com", "status": "ASSOCIATED WITH APPLICATION", "system": False},
        {"name": "journal", "type": "MariaDB", "application_id": "ojs:/var/www/journal.50sea.com", "status": "ASSOCIATED WITH APPLICATION", "system": False},
        {"name": "sea_tedb", "type": "MariaDB", "application_id": "wordpress:/var/www/50sea.com", "status": "ASSOCIATED WITH APPLICATION", "system": False},
        {"name": "xdgen_db", "type": "MariaDB", "application_id": "", "status": "UNASSOCIATED DATABASE — REQUIRES REVIEW", "system": False},
        {"name": "mysql", "type": "MariaDB", "application_id": "", "status": "SYSTEM DATABASE — EXCLUDED", "system": True},
    ]


def test_sanitize_domain_folder_rejects_path_parts():
    assert sanitize_domain_folder("50sea.com") == "50sea.com"
    assert ".." not in sanitize_domain_folder("foo..bar.com")
    assert "/" not in sanitize_domain_folder("evil/50sea.com")
    assert "\\" not in sanitize_domain_folder("evil\\50sea.com")


def test_domain_map_one_folder_per_site_and_correct_databases():
    mapping = build_domain_map(_apps(), _inventory())
    folders = [site.folder for site in mapping.sites]
    assert folders.count("50sea.com") == 1
    assert "journal.50sea.com" in folders
    assert "citation.xdgen.com" in folders
    assert "_" not in folders
    assert "html" not in folders
    sea = mapping.site_by_folder("50sea.com")
    journal = mapping.site_by_folder("journal.50sea.com")
    assert sea is not None and journal is not None
    assert {db.name for db in sea.databases} == {"sea_tedb"}
    assert {db.name for db in journal.databases} == {"ojs50", "journal"}
    assert "sea_tedb" not in {db.name for db in journal.databases}
    assert "ojs50" not in {db.name for db in sea.databases}
    assert [db.name for db in mapping.unassigned_databases] == ["xdgen_db"]
    citation = mapping.site_by_folder("citation.xdgen.com")
    assert citation is not None
    assert citation.named_volumes == ["citation_pgdata"]
    assert citation.docker is not None
    mariadb, postgres = dump_names(mapping, selected=[])
    assert "sea_tedb" in mariadb
    assert "ojs50" in mariadb
    assert "citation" in postgres
    assert "xdgen_db" not in mariadb


def test_overlay2_is_blocked_from_site_folders():
    mapping = build_domain_map(_apps(), _inventory())
    placement = classify_file(
        {
            "source_root": "/var/lib/docker/overlay2/abc",
            "relative_path": "merged/var/www/html/index.html",
            "sha256": "abc",
        },
        mapping,
        nginx_root="/etc/nginx",
    )
    assert placement["kind"] == "blocked"
    assert placement["site_folder"] == ""


def test_files_are_classified_under_the_owning_domain():
    mapping = build_domain_map(_apps(), _inventory())
    sea = classify_file(
        {"source_root": "/var/www/50sea.com", "relative_path": "index.html"},
        mapping,
        nginx_root="/etc/nginx",
    )
    journal_app = classify_file(
        {"source_root": "/var/www/journal.50sea.com", "relative_path": "index.php"},
        mapping,
        nginx_root="/etc/nginx",
    )
    journal_storage = classify_file(
        {"source_root": "/var/lib/ojs-journal50", "relative_path": "paper.pdf"},
        mapping,
        nginx_root="/etc/nginx",
    )
    assert sea["site_folder"] == "50sea.com" and sea["kind"] == "application"
    assert journal_app["site_folder"] == "journal.50sea.com"
    assert journal_storage["kind"] == "storage"
    assert journal_storage["site_folder"] == "journal.50sea.com"
    nginx = classify_file(
        {"source_root": "/etc/nginx", "relative_path": "sites-enabled/50sea.com"},
        mapping,
        nginx_root="/etc/nginx",
    )
    assert nginx["site_folder"] == "50sea.com"
    assert nginx["kind"] == "config"
    shared = classify_file(
        {"source_root": "/etc/nginx", "relative_path": "nginx.conf"},
        mapping,
        nginx_root="/etc/nginx",
    )
    assert shared["site_folder"] == "_server"


def test_readable_export_from_master_objects(tmp_path: Path):
    dest = tmp_path / "ServerBackups"
    dest.mkdir()
    store = MasterStore(dest)
    store.ensure_layout()
    html = write_object_from_bytes(store.objects_root, b"50sea-index")
    wp = write_object_from_bytes(store.objects_root, b"define('DB_NAME', 'sea_tedb');\n")
    journal = write_object_from_bytes(store.objects_root, b"journal50-app\n")
    paper = write_object_from_bytes(store.objects_root, b"%PDF-50sea")
    nginx = write_object_from_bytes(store.objects_root, b"events {}\n")
    dump = write_object_from_bytes(store.objects_root, __import__("gzip").compress(b"SQL sea_tedb"))
    ojs_dump = write_object_from_bytes(store.objects_root, __import__("gzip").compress(b"SQL ojs50"))
    unassigned = write_object_from_bytes(store.objects_root, __import__("gzip").compress(b"SQL xdgen_db"))
    tree = {
        "generation": 1,
        "timestamp": "2026-09-16 00:00:00",
        "files": [
            make_record(source_root="/var/www/50sea.com", relative_path="index.html", sha256=html, category="website"),
            make_record(source_root="/var/www/50sea.com", relative_path="wp-config.php", sha256=wp, category="website"),
            make_record(source_root="/var/www/journal.50sea.com", relative_path="index.php", sha256=journal, category="website"),
            make_record(source_root="/var/lib/ojs-journal50", relative_path="paper.pdf", sha256=paper, category="ojs"),
            make_record(source_root="/etc/nginx", relative_path="nginx.conf", sha256=nginx, category="nginx"),
        ],
        "database_objects": {"sea_tedb": dump, "ojs50": ojs_dump, "xdgen_db": unassigned},
    }
    test_root = tmp_path / "BACKUPS-TEST"
    manifest = export_readable_backup(
        destination=dest,
        store=store,
        tree=tree,
        applications=_apps(),
        database_inventory=_inventory(),
        meta={"database_objects": tree["database_objects"]},
        timestamp="2026-09-16 00:00:00",
        generation=1,
        output_root=test_root,
    )
    assert (dest / "master").is_dir()
    assert not (dest / READABLE_DIR).exists()
    assert (test_root / "BACKUP-MANIFEST.json").is_file()
    assert (test_root / "50sea.com" / "files" / "application" / "index.html").read_bytes() == b"50sea-index"
    assert (test_root / "50sea.com" / "files" / "config" / "wp-config.php").is_file()
    assert (test_root / "50sea.com" / "database" / "sea_tedb.sql").read_bytes() == b"SQL sea_tedb"
    assert (test_root / "journal.50sea.com" / "files" / "storage" / "paper.pdf").read_bytes() == b"%PDF-50sea"
    assert (test_root / "journal.50sea.com" / "database" / "ojs50.sql").read_bytes() == b"SQL ojs50"
    assert not (test_root / "50sea.com" / "database" / "ojs50.sql").exists()
    assert not (test_root / "journal.50sea.com" / "database" / "sea_tedb.sql").exists()
    assert (test_root / "_unassigned-databases" / "xdgen_db.sql").read_bytes() == b"SQL xdgen_db"
    assert (test_root / "_server" / "nginx" / "nginx.conf").is_file()
    assert (test_root / "citation.xdgen.com" / "docker" / "container-info.txt").is_file()
    assert (test_root / "50sea.com" / "backup-info.txt").read_text(encoding="utf-8").startswith("Domain: 50sea.com")
    payload = json.loads((test_root / "BACKUP-MANIFEST.json").read_text(encoding="utf-8"))
    domains = [row["domain"] for row in payload["websites"]]
    assert domains.count("50sea.com") == 1
    assert "journal.50sea.com" in domains
    assert manifest["unassigned_databases"][0]["name"] == "xdgen_db"
    overlay = list(test_root.rglob("*"))
    assert not any("overlay2" in str(path) or "citation_pgdata" == path.name for path in overlay)


def test_backup_now_writes_per_domain_tree_and_keeps_master_and_legacy(tmp_path: Path):
    remote = seed_remote_tree(tmp_path / "remote")
    cfg = master_config(tmp_path, remote)
    dest = Path(cfg.backup_destination)
    write_success_backup(dest, "2026-09-07_082000")
    enable_backup(cfg, LocalMasterSSH(tmp_path / "remote"))
    info = BackupEngine(cfg, ssh=LocalMasterSSH(tmp_path / "remote")).run()
    assert info["status"] == "SUCCESS"
    assert (dest / "master" / "HEAD").is_file()
    assert (dest / "2026-09-07_082000" / "backup-info.json").is_file()
    backups = readable_root(dest)
    assert (backups / "BACKUP-MANIFEST.json").is_file()
    manifest = json.loads((backups / "BACKUP-MANIFEST.json").read_text(encoding="utf-8"))
    domains = [row["domain"] for row in manifest["websites"]]
    assert len(domains) == len(set(domains))
    assert "50sea.com" in domains
    assert "journal.50sea.com" in domains
    assert "journal.xdgen.com" in domains
    assert "xdgen.com" in domains
    assert (backups / "50sea.com" / "files" / "application" / "index.html").read_text(encoding="utf-8") == "50sea\n"
    assert "sea_tedb" in (backups / "50sea.com" / "files" / "application" / "wp-config.php").read_text(encoding="utf-8")
    assert (backups / "50sea.com" / "database" / "sea_tedb.sql").is_file()
    assert "SQL sea_tedb" in (backups / "50sea.com" / "database" / "sea_tedb.sql").read_text(encoding="utf-8", errors="replace")
    assert (backups / "journal.50sea.com" / "files" / "application" / "index.php").is_file()
    assert (backups / "journal.50sea.com" / "files" / "storage" / "paper.pdf").is_file()
    assert (backups / "journal.50sea.com" / "database" / "ojs50.sql").is_file()
    assert not (backups / "50sea.com" / "database" / "ojs50.sql").exists()
    assert not (backups / "journal.50sea.com" / "database" / "sea_tedb.sql").exists()
    sea_text = (backups / "50sea.com" / "files" / "application" / "index.html").read_text(encoding="utf-8")
    journal_index = (backups / "journal.50sea.com" / "files" / "application" / "index.php").read_text(encoding="utf-8")
    assert "journal50-app" not in sea_text
    assert "50sea\n" not in journal_index
    assert (backups / "citation.xdgen.com" / "docker" / "container-info.json").is_file()
    assert not (backups / "html").exists()
    names = [path.name for path in backups.iterdir() if path.is_dir()]
    assert all(not name.startswith("objects") for name in names)
    assert info["readable"]["status"] == "SUCCESS"
