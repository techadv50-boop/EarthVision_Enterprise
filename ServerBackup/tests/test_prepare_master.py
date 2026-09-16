import json
from pathlib import Path

from tests.helpers import UBUNTU_SCRIPTS, seed_remote_tree


def test_discover_ojs_finds_both_files_dir(tmp_path: Path):
    import sys

    if str(UBUNTU_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(UBUNTU_SCRIPTS))
    import prepare_master as pm

    remote = seed_remote_tree(tmp_path)
    result = pm.discover_ojs(
        {
            "website_directories": [
                remote["journal.50sea.com"],
                remote["journal.xdgen.com"],
                remote["xdgen.com"],
                remote["50sea.com"],
            ]
        }
    )
    assert result["ok"] is True
    mapping = {item["domain"]: item["files_dir"] for item in result["installations"]}
    assert mapping["journal.50sea.com"] == remote["ojs50"]
    assert mapping["journal.xdgen.com"] == remote["ojsxd"]
    assert "xdgen.com" not in mapping
    assert "50sea.com" not in mapping


def test_discover_ojs_fails_when_files_dir_missing(tmp_path: Path):
    import sys
    import shutil

    if str(UBUNTU_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(UBUNTU_SCRIPTS))
    import prepare_master as pm

    remote = seed_remote_tree(tmp_path)
    shutil.rmtree(remote["ojs50"])
    result = pm.discover_ojs({"website_directories": [remote["journal.50sea.com"]]})
    assert result["ok"] is False
    assert any("does not exist" in err for err in result["errors"])


def test_inventory_does_not_copy_ojs_into_tmp(tmp_path: Path):
    import sys

    if str(UBUNTU_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(UBUNTU_SCRIPTS))
    import prepare_master as pm

    remote = seed_remote_tree(tmp_path)
    result = pm.inventory(
        {
            "sources": [
                {"root": remote["journal.50sea.com"], "category": "website"},
                {"root": remote["ojs50"], "category": "ojs"},
            ]
        }
    )
    assert result["ok"] is True
    assert result["files"]
    tmp_children = list(Path("/tmp").glob("ojs-journal50*"))
    assert tmp_children == [] or all("ojs-journal50" not in str(p) for p in tmp_children)


def test_prepare_helper_allows_master_actions():
    import subprocess

    from app.ssh.client import bundled_ubuntu_scripts

    script = bundled_ubuntu_scripts() / "prepare-backup.sh"
    for action in ("discover-ojs", "inventory", "hash-files", "database-fingerprint"):
        result = subprocess.run(
            ["bash", str(script)],
            input=json.dumps({"action": action, "website_directories": [], "sources": [], "paths": [], "databases": []}),
            text=True,
            capture_output=True,
            cwd=str(script.parent),
        )
        combined = result.stderr + result.stdout
        assert "action not allowed" not in combined, action


def test_database_fingerprint_uses_docker_exec_for_container_schema():
    import sys

    if str(UBUNTU_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(UBUNTU_SCRIPTS))
    import prepare_master as pm

    calls: list[list[str]] = []

    class _Result:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "wp_posts\n"
            self.stderr = ""

    def run(cmd, timeout=None):
        calls.append(list(cmd))
        return _Result()

    result = pm.database_fingerprint(
        {"databases": ["sea50_db"], "docker_databases": {"sea50_db": "sea50-cyfdw1-db-1"}},
        run,
        lambda: ["--defaults-extra-file=/etc/serverbackup/my.cnf"],
    )
    assert result["ok"] is True
    assert result["fingerprints"][0]["name"] == "sea50_db"
    assert calls
    assert calls[0][:4] == ["docker", "exec", "sea50-cyfdw1-db-1", "mysql"]
    assert "--defaults-extra-file=/etc/serverbackup/my.cnf" not in calls[0]


def test_database_fingerprint_rejects_unsafe_docker_name():
    import sys

    if str(UBUNTU_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(UBUNTU_SCRIPTS))
    import prepare_master as pm

    result = pm.database_fingerprint(
        {"databases": ["sea50_db"], "docker_databases": {"sea50_db": "sea50;rm -rf /"}},
        lambda *_args, **_kwargs: None,
        lambda: [],
    )
    assert result["ok"] is False
    assert any("unsafe docker" in err for err in result["errors"])


def test_database_fingerprint_does_not_query_host_for_missing_schema():
    import sys

    if str(UBUNTU_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(UBUNTU_SCRIPTS))
    import prepare_master as pm

    calls: list[list[str]] = []

    class _Result:
        returncode = 1
        stdout = ""
        stderr = "ERROR 1049 (42000): Unknown database 'sea50_db'"

    def run(cmd, timeout=None):
        calls.append(list(cmd))
        return _Result()

    result = pm.database_fingerprint(
        {
            "databases": ["sea50_db"],
            "docker_databases": {},
            "host_databases": ["sea_tecdb", "journal50_ojs", "journal_db", "xdgen_db"],
        },
        run,
        lambda: ["--defaults-extra-file=/etc/serverbackup/my.cnf"],
    )
    assert result["ok"] is False
    assert any("not on host MariaDB" in err for err in result["errors"])
    assert calls == []


def test_database_fingerprint_falls_back_to_mariadb_client():
    import sys

    if str(UBUNTU_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(UBUNTU_SCRIPTS))
    import prepare_master as pm

    calls: list[list[str]] = []

    class _Result:
        def __init__(self, code: int, stderr: str = "", stdout: str = "") -> None:
            self.returncode = code
            self.stdout = stdout
            self.stderr = stderr

    def run(cmd, timeout=None):
        calls.append(list(cmd))
        if cmd[3] == "mysql":
            return _Result(127, "executable file not found")
        return _Result(0, stdout="wp_posts\n")

    result = pm.database_fingerprint(
        {"databases": ["sea50_db"], "docker_databases": {"sea50_db": "sea50-cyfdw1-db-1"}},
        run,
        lambda: [],
    )
    assert result["ok"] is True
    binaries = [call[3] for call in calls]
    assert "mysql" in binaries
    assert "mariadb" in binaries

