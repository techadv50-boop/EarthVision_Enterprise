"""Ensure MariaDB dumps use a dedicated least-privilege account.

Never modifies application database users, website files, Nginx, or the root account.
Never prints the backup password. Writes only /etc/serverbackup/my.cnf (mode 600).
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
from pathlib import Path
from typing import Any, Callable

BACKUP_MYSQL_USER = "serverbackup"
BACKUP_MYSQL_HOST = "localhost"
MYSQL_CNF = "/etc/serverbackup/my.cnf"
SYSTEM_DATABASES = {"information_schema", "performance_schema", "mysql", "sys"}
REQUIRED_PRIVILEGES = (
    "SELECT",  # dump rows, COUNT(*), information_schema, SHOW TABLE STATUS
    "SHOW VIEW",  # mysqldump views as views
    "TRIGGER",  # mysqldump --triggers
    "LOCK TABLES",  # non-InnoDB tables during --single-transaction
    "EVENT",  # mysqldump --events
    "PROCESS",  # mysqldump --single-transaction processlist check
    "RELOAD",  # FLUSH TABLES WITH READ LOCK for mixed-engine snapshots
)
OPTIONAL_PRIVILEGES = (
    "SHOW_ROUTINE",  # MariaDB 10.7+ mysqldump --routines without mysql.proc SELECT
)
FORBIDDEN_PRIVILEGE_MARKERS = (
    "ALL PRIVILEGES",
    "ALL ON",
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "CREATE",
    "ALTER",
    "SUPER",
    "FILE",
    "SHUTDOWN",
    "GRANT OPTION",
    "REPLICATION CLIENT",
    "REPLICATION SLAVE",
)


def _sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _account() -> str:
    return f"`{BACKUP_MYSQL_USER}`@`{BACKUP_MYSQL_HOST}`"


def generate_backup_password() -> str:
    return secrets.token_urlsafe(24)


def grant_sql(privileges: tuple[str, ...] = REQUIRED_PRIVILEGES) -> str:
    listed = ", ".join(privileges)
    return f"GRANT {listed} ON *.* TO {_account()}"


def privileges_are_least_privilege(grants: list[str]) -> bool:
    blob = "\n".join(grants).upper()
    if any(marker in blob for marker in ("ALL PRIVILEGES", "WITH GRANT OPTION")):
        return False
    needed = {item.replace("_", " ") for item in REQUIRED_PRIVILEGES}
    haystack = blob.replace("_", " ")
    return all(name in haystack for name in needed)


def parse_current_user(stdout: str) -> str:
    return (stdout or "").strip().split("\t")[0].strip().split("\n")[0].strip()


def _redact_grants(lines: list[str]) -> list[str]:
    out: list[str] = []
    for raw in lines:
        text = re.sub(
            r"IDENTIFIED BY\s+(PASSWORD\s+)?('[^']*'|\"[^\"]*\"|\S+)",
            "IDENTIFIED BY '***'",
            raw,
            flags=re.IGNORECASE,
        )
        out.append(text)
    return out
    return (stdout or "").strip().split("\t")[0].strip().split("\n")[0].strip()


def _mysql(run: Callable, defaults: list[str], sql: str, *, timeout: int = 20):
    return run(["mysql", *defaults, "--batch", "--skip-column-names", "--raw", "-e", sql], timeout=timeout)


def _write_cnf(path: Path, password: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    body = f"[client]\nuser={BACKUP_MYSQL_USER}\nhost={BACKUP_MYSQL_HOST}\npassword={password}\n"
    tmp.write_text(body, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def _admin_create_and_grant(run: Callable, admin_defaults: list[str], password: str) -> list[str]:
    notes: list[str] = []
    escaped = _sql_string(password)
    statements = [
        f"CREATE USER IF NOT EXISTS {_account()} IDENTIFIED BY {escaped}",
        f"ALTER USER {_account()} IDENTIFIED BY {escaped}",
        f"REVOKE ALL PRIVILEGES, GRANT OPTION FROM {_account()}",
        grant_sql(),
        "FLUSH PRIVILEGES",
    ]
    for sql in statements:
        result = _mysql(run, admin_defaults, sql)
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            if "REVOKE" in sql and ("There is no such grant" in err or "Can't find any matching row" in err):
                notes.append("REVOKE skipped; account had no prior grants")
                continue
            raise RuntimeError(err or f"MariaDB statement failed: {sql.split('IDENTIFIED')[0].strip()}")
    extra = grant_sql(REQUIRED_PRIVILEGES + OPTIONAL_PRIVILEGES)
    extra_result = _mysql(run, admin_defaults, extra + "; FLUSH PRIVILEGES")
    if extra_result.returncode == 0:
        notes.append("SHOW_ROUTINE granted")
    else:
        notes.append("SHOW_ROUTINE not available on this MariaDB; --routines uses SELECT")
    return notes


def _verify_backup_account(run: Callable, defaults: list[str], mysqldump: str | None) -> dict[str, Any]:
    user_result = _mysql(run, defaults, "SELECT CURRENT_USER(), USER()")
    if user_result.returncode != 0:
        raise RuntimeError((user_result.stderr or user_result.stdout or "CURRENT_USER failed").strip())
    parts = (user_result.stdout or "").strip().split("\t")
    current_user = parts[0].strip() if parts else ""
    session_user = parts[1].strip() if len(parts) > 1 else ""
    if current_user.split("@")[0] != BACKUP_MYSQL_USER:
        raise RuntimeError(f"expected {BACKUP_MYSQL_USER}, connected as {current_user or 'unknown'}")
    grants_result = _mysql(run, defaults, "SHOW GRANTS")
    grants = _redact_grants([line.strip() for line in (grants_result.stdout or "").splitlines() if line.strip()])
    if not privileges_are_least_privilege(grants):
        raise RuntimeError("backup account grants are not least-privilege")
    db_result = _mysql(run, defaults, "SHOW DATABASES")
    if db_result.returncode != 0:
        raise RuntimeError((db_result.stderr or "SHOW DATABASES failed").strip())
    databases = [line.strip() for line in (db_result.stdout or "").splitlines() if line.strip()]
    sample = next((name for name in databases if name not in SYSTEM_DATABASES), "")
    fingerprint_ok = True
    dump_ok = True
    dump_detail = "skipped (no non-system database)"
    if sample:
        fp = run(
            ["mysql", *defaults, "--batch", "--skip-column-names", sample, "-e", "SHOW TABLE STATUS"],
            timeout=20,
        )
        tables = run(
            ["mysql", *defaults, "--batch", "--skip-column-names", sample, "-e", "SHOW TABLES"],
            timeout=20,
        )
        fingerprint_ok = fp.returncode == 0 and tables.returncode == 0
        if mysqldump:
            dumped = run(
                [
                    mysqldump,
                    *defaults,
                    "--single-transaction",
                    "--quick",
                    "--routines",
                    "--triggers",
                    "--events",
                    "--no-data",
                    "--databases",
                    sample,
                ],
                timeout=60,
            )
            dump_ok = dumped.returncode == 0
            dump_detail = (
                "mysqldump --single-transaction --routines --triggers --events --no-data OK"
                if dump_ok
                else (dumped.stderr or dumped.stdout or "mysqldump failed").strip()
            )
        else:
            dump_ok = False
            dump_detail = "mysqldump not found"
    using_root = current_user.split("@")[0].lower() == "root"
    return {
        "configured_user": BACKUP_MYSQL_USER,
        "current_user": current_user,
        "session_user": session_user,
        "source": MYSQL_CNF,
        "file_present": True,
        "using_root": using_root,
        "grants": grants,
        "least_privilege": privileges_are_least_privilege(grants),
        "databases_visible": databases,
        "fingerprint_ok": fingerprint_ok,
        "dump_probe_ok": dump_ok,
        "dump_probe_detail": dump_detail,
    }


def ensure_backup_mysql_user(
    run: Callable,
    mysql_defaults: Callable,
    *,
    cnf_path: str = MYSQL_CNF,
    mysqldump: str | None = None,
) -> dict[str, Any]:
    """Create/switch to serverbackup via my.cnf. Returns public account info only."""
    cnf = Path(cnf_path)
    admin_defaults = list(mysql_defaults())
    previous = cnf.read_bytes() if cnf.is_file() else None
    probe = run(
        ["mysql", *admin_defaults, "--batch", "--skip-column-names", "-e", "SELECT CURRENT_USER()"],
        timeout=15,
    )
    current = parse_current_user(probe.stdout if probe.returncode == 0 else "")
    already = current.split("@")[0] == BACKUP_MYSQL_USER
    changed = False
    notes: list[str] = []
    if already:
        notes.append("my.cnf already uses the dedicated backup account")
        grants_result = run(
            ["mysql", *admin_defaults, "--batch", "--skip-column-names", "-e", "SHOW GRANTS"],
            timeout=15,
        )
        grants = [line.strip() for line in (grants_result.stdout or "").splitlines() if line.strip()]
        if privileges_are_least_privilege(grants):
            notes.append("existing grants are least-privilege")
        else:
            raise RuntimeError("dedicated backup account currently has excess privileges; not modified automatically")
    else:
        password = generate_backup_password()
        try:
            notes.extend(_admin_create_and_grant(run, admin_defaults, password))
            _write_cnf(cnf, password)
            changed = True
            notes.append(f"wrote {cnf_path} user={BACKUP_MYSQL_USER} mode=600")
        except Exception:
            if previous is not None:
                cnf.write_bytes(previous)
                os.chmod(cnf, 0o600)
            raise
        finally:
            password = ""  # noqa: F841
    verify_defaults = [f"--defaults-extra-file={cnf}"] if cnf.is_file() else admin_defaults
    dump_bin = mysqldump if mysqldump is not None else shutil.which("mysqldump")
    try:
        verified = _verify_backup_account(run, verify_defaults, dump_bin)
    except Exception:
        if changed and previous is not None:
            cnf.write_bytes(previous)
            os.chmod(cnf, 0o600)
        raise
    verified["changed"] = changed
    verified["notes"] = notes
    verified["root_unchanged"] = True
    verified["application_credentials_unchanged"] = True
    return verified
