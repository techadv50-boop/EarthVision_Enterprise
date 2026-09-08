from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

from app.security.allowlist import is_allowed_remote_action
from tests.helpers import UBUNTU_SCRIPTS

if str(UBUNTU_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(UBUNTU_SCRIPTS))
import mysql_backup_user as mbu  # noqa: E402


class _Result:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_required_privileges_are_least_privilege_not_all():
    sql = mbu.grant_sql()
    assert "ALL PRIVILEGES" not in sql
    assert "GRANT OPTION" not in sql
    assert "INSERT" not in sql
    assert "UPDATE" not in sql
    assert "DELETE" not in sql
    assert "DROP" not in sql
    for name in mbu.REQUIRED_PRIVILEGES:
        assert name in sql
    grants = [
        "GRANT SELECT, SHOW VIEW, TRIGGER, LOCK TABLES, EVENT, PROCESS, RELOAD ON *.* TO `serverbackup`@`localhost`"
    ]
    assert mbu.privileges_are_least_privilege(grants) is True
    assert mbu.privileges_are_least_privilege(["GRANT ALL PRIVILEGES ON *.* TO `root`@`localhost`"]) is False


def test_ensure_writes_serverbackup_cnf_without_exposing_password(tmp_path: Path, monkeypatch):
    cnf = tmp_path / "my.cnf"
    cnf.write_text("[client]\nuser=root\npassword=rootsecret\n", encoding="utf-8")
    monkeypatch.setattr(mbu, "generate_backup_password", lambda: "backup-secret-value")
    monkeypatch.setattr(mbu, "MYSQL_CNF", str(cnf))
    state = {"user": "root@localhost"}

    def run(cmd, timeout=20):
        joined = " ".join(cmd)
        defaults = [part for part in cmd if part.startswith("--defaults-extra-file=")]
        using_backup = False
        if defaults:
            path = Path(defaults[0].split("=", 1)[1])
            if path.is_file() and "user=serverbackup" in path.read_text(encoding="utf-8"):
                using_backup = True
                assert "backup-secret-value" in path.read_text(encoding="utf-8")
        if "CURRENT_USER" in joined:
            if using_backup:
                return _Result("serverbackup@localhost\tserverbackup@localhost\n")
            return _Result("root@localhost\n")
        if "SHOW GRANTS" in joined:
            if using_backup:
                return _Result(
                    "GRANT SELECT, SHOW VIEW, TRIGGER, LOCK TABLES, EVENT, PROCESS, RELOAD ON *.* "
                    "TO `serverbackup`@`localhost` IDENTIFIED BY 'backup-secret-value'\n"
                )
            return _Result("GRANT ALL PRIVILEGES ON *.* TO `root`@`localhost`\n")
        if "SHOW DATABASES" in joined:
            return _Result("information_schema\nsea_tedb\njournal50_ojs\njournal_db\nxdgen_db\n")
        if "SHOW TABLE STATUS" in joined or "SHOW TABLES" in joined:
            return _Result("wp_posts\n")
        if cmd and "mysqldump" in cmd[0]:
            assert "--single-transaction" in cmd
            assert "--no-data" in cmd
            return _Result("")
        if "CREATE USER" in joined or "ALTER USER" in joined or "GRANT" in joined or "REVOKE" in joined or "FLUSH" in joined:
            assert "rootsecret" not in joined
            return _Result("")
        return _Result("")

    result = mbu.ensure_backup_mysql_user(run, lambda: [f"--defaults-extra-file={cnf}"], cnf_path=str(cnf), mysqldump="mysqldump")
    blob = json.dumps(result)
    assert result["configured_user"] == "serverbackup"
    assert result["current_user"] == "serverbackup@localhost"
    assert result["using_root"] is False
    assert result["least_privilege"] is True
    assert result["dump_probe_ok"] is True
    assert result["fingerprint_ok"] is True
    assert result["root_unchanged"] is True
    assert "backup-secret-value" not in blob
    assert "rootsecret" not in blob
    text = cnf.read_text(encoding="utf-8")
    assert "user=serverbackup" in text
    assert stat.S_IMODE(cnf.stat().st_mode) == 0o600
    assert "ALL PRIVILEGES" not in "\n".join(result["grants"])


def test_ensure_leaves_existing_serverbackup_account(tmp_path: Path):
    cnf = tmp_path / "my.cnf"
    cnf.write_text("[client]\nuser=serverbackup\npassword=already-set\n", encoding="utf-8")

    def run(cmd, timeout=20):
        joined = " ".join(cmd)
        if "CURRENT_USER" in joined:
            return _Result("serverbackup@localhost\tserverbackup@localhost\n")
        if "SHOW GRANTS" in joined:
            return _Result(
                "GRANT SELECT, SHOW VIEW, TRIGGER, LOCK TABLES, EVENT, PROCESS, RELOAD ON *.* TO `serverbackup`@`localhost`\n"
            )
        if "SHOW DATABASES" in joined:
            return _Result("sea_tedb\n")
        if "SHOW TABLE STATUS" in joined or "SHOW TABLES" in joined:
            return _Result("t\n")
        if cmd and "mysqldump" in cmd[0]:
            return _Result("")
        if "ALTER USER" in joined or "CREATE USER" in joined:
            raise AssertionError("must not rotate an already-correct backup account")
        return _Result("")

    result = mbu.ensure_backup_mysql_user(run, lambda: [f"--defaults-extra-file={cnf}"], cnf_path=str(cnf), mysqldump="mysqldump")
    assert result["changed"] is False
    assert "already-set" not in json.dumps(result)


def test_ensure_action_is_allowlisted():
    assert is_allowed_remote_action("ensure-backup-mysql-user")
    script = (UBUNTU_SCRIPTS / "prepare-backup.sh").read_text(encoding="utf-8")
    assert "ensure-backup-mysql-user" in script
    assert (UBUNTU_SCRIPTS / "mysql_backup_user.py").is_file()
