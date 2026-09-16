"""Read-only MariaDB access inside a Docker db container.

Credentials stay inside the container env (MYSQL_ROOT_PASSWORD / MARIADB_*).
They are never printed, logged, or returned to Windows.
"""

from __future__ import annotations

from path_safety import require_docker_name

ALLOWED_SQL = frozenset({"SHOW TABLE STATUS", "SHOW TABLES"})

# $1 = database name, $2 = SQL (fingerprint only).
MYSQL_QUERY_SH = r"""
db="$1"
sql="$2"
client() {
  if command -v mysql >/dev/null 2>&1; then
    mysql "$@"
  elif command -v mariadb >/dev/null 2>&1; then
    mariadb "$@"
  else
    echo "mysql client was not found in the database container" >&2
    return 127
  fi
}
try_query() {
  client --batch --skip-column-names "$@" -e "$sql" "$db"
}
if try_query; then
  exit 0
fi
pw="${MYSQL_ROOT_PASSWORD:-${MARIADB_ROOT_PASSWORD:-}}"
if [ -z "$pw" ] && [ -n "${MYSQL_ROOT_PASSWORD_FILE:-}" ] && [ -f "$MYSQL_ROOT_PASSWORD_FILE" ]; then
  pw=$(cat "$MYSQL_ROOT_PASSWORD_FILE")
fi
if [ -z "$pw" ] && [ -n "${MARIADB_ROOT_PASSWORD_FILE:-}" ] && [ -f "$MARIADB_ROOT_PASSWORD_FILE" ]; then
  pw=$(cat "$MARIADB_ROOT_PASSWORD_FILE")
fi
if [ -n "$pw" ]; then
  MYSQL_PWD="$pw" try_query -uroot && exit 0
fi
user="${MYSQL_USER:-${MARIADB_USER:-}}"
upw="${MYSQL_PASSWORD:-${MARIADB_PASSWORD:-}}"
if [ -n "$user" ] && [ -n "$upw" ]; then
  MYSQL_PWD="$upw" try_query -u"$user" && exit 0
fi
exit 1
"""

# $1 = database name. Successful dump writes SQL to stdout only.
MYSQL_DUMP_SH = r"""
db="$1"
dump() {
  if command -v mysqldump >/dev/null 2>&1; then
    mysqldump "$@"
  elif command -v mariadb-dump >/dev/null 2>&1; then
    mariadb-dump "$@"
  else
    echo "mysqldump was not found in the database container" >&2
    return 127
  fi
}
flags() {
  dump "$@" --single-transaction --quick --routines --triggers --events --hex-blob --databases "$db"
}
if flags; then
  exit 0
fi
pw="${MYSQL_ROOT_PASSWORD:-${MARIADB_ROOT_PASSWORD:-}}"
if [ -z "$pw" ] && [ -n "${MYSQL_ROOT_PASSWORD_FILE:-}" ] && [ -f "$MYSQL_ROOT_PASSWORD_FILE" ]; then
  pw=$(cat "$MYSQL_ROOT_PASSWORD_FILE")
fi
if [ -z "$pw" ] && [ -n "${MARIADB_ROOT_PASSWORD_FILE:-}" ] && [ -f "$MARIADB_ROOT_PASSWORD_FILE" ]; then
  pw=$(cat "$MARIADB_ROOT_PASSWORD_FILE")
fi
if [ -n "$pw" ]; then
  MYSQL_PWD="$pw" flags -uroot && exit 0
fi
user="${MYSQL_USER:-${MARIADB_USER:-}}"
upw="${MYSQL_PASSWORD:-${MARIADB_PASSWORD:-}}"
if [ -n "$user" ] && [ -n "$upw" ]; then
  MYSQL_PWD="$upw" flags -u"$user" && exit 0
fi
exit 1
"""


def _safe_db_name(name: str) -> str:
    cleaned = str(name or "").strip()
    if not cleaned or any(ch in cleaned for ch in ";&|`$<>\\\n\r") or "/" in cleaned or " " in cleaned:
        raise ValueError(f"Refusing unsafe database name: {name!r}")
    return cleaned


def docker_mysql_argv(container: str, database: str, sql: str) -> list[str]:
    safe_container = require_docker_name(container)
    db_name = _safe_db_name(database)
    statement = str(sql or "").strip().upper()
    if statement not in ALLOWED_SQL:
        raise ValueError(f"Refusing unsafe SQL for container fingerprint: {sql!r}")
    return [
        "docker",
        "exec",
        safe_container,
        "sh",
        "-c",
        MYSQL_QUERY_SH,
        "serverbackup-mysql",
        db_name,
        statement,
    ]


def docker_dump_argv(container: str, database: str) -> list[str]:
    safe_container = require_docker_name(container)
    db_name = _safe_db_name(database)
    return [
        "docker",
        "exec",
        safe_container,
        "sh",
        "-c",
        MYSQL_DUMP_SH,
        "serverbackup-dump",
        db_name,
    ]


def parse_show_table_status(stdout: str) -> dict[str, int]:
    """Sum Data_length + Index_length from `SHOW TABLE STATUS` batch output.

    Column order (skip-column-names): Name, Engine, Version, Row_format, Rows,
    Avg_row_length, Data_length, Max_data_length, Index_length, ...
    """
    size = 0
    rows = 0
    tables = 0
    for line in (stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 9:
            continue
        name = (parts[0] or "").strip()
        if not name or name.upper() in {"NAME", "TABLE"}:
            continue
        tables += 1
        try:
            rows += int(parts[4] or 0)
        except ValueError:
            pass
        try:
            size += int(parts[6] or 0) + int(parts[8] or 0)
        except ValueError:
            pass
    return {"size_bytes": size, "table_count": tables, "row_count": rows}


def docker_schema_details(run, container: str, database: str) -> dict:
    """Read-only size/table probe inside a Docker MariaDB/MySQL container. Never dumps."""
    argv = docker_mysql_argv(container, database, "SHOW TABLE STATUS")
    try:
        result = run(argv, timeout=30)
    except Exception as exc:  # noqa: BLE001
        return {
            "size_bytes": None,
            "table_count": None,
            "row_count": None,
            "probe": f"SHOW TABLE STATUS failed: {exc}",
            "dump_capable": False,
        }
    code = getattr(result, "returncode", 1)
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    if code != 0:
        detail = (stderr or stdout or "docker exec mysql failed").strip().splitlines()
        safe = detail[0][:200] if detail else "docker exec mysql failed"
        return {
            "size_bytes": None,
            "table_count": None,
            "row_count": None,
            "probe": safe,
            "dump_capable": False,
        }
    parsed = parse_show_table_status(stdout)
    parsed["probe"] = "SHOW TABLE STATUS via docker exec succeeded (read-only; dump not executed)"
    parsed["dump_capable"] = True
    return parsed
