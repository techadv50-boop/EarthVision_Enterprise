"""Read-only MariaDB and PostgreSQL access inside a Docker db container.

Credentials stay inside the container env. They are never printed, logged, or
returned to Windows. MySQL clients are never used against PostgreSQL.
"""

from __future__ import annotations

from path_safety import require_docker_name

ALLOWED_SQL = frozenset({"SHOW TABLE STATUS", "SHOW TABLES"})
ALLOWED_PG_SQL = frozenset(
    {
        "SELECT 1",
        "SIZE_AND_TABLES",
        "SCHEMA_LIST",
        "META",
    }
)
PG_SIZE_SQL = (
    "SELECT pg_database_size(current_database()), "
    "(SELECT count(*) FROM information_schema.tables "
    "WHERE table_schema NOT IN ('pg_catalog','information_schema') AND table_type='BASE TABLE'), "
    "(SELECT COALESCE(sum(n_live_tup),0) FROM pg_stat_user_tables)"
)
PG_SCHEMA_SQL = (
    "SELECT tablename FROM pg_tables "
    "WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY tablename"
)
PG_META_SQL = (
    "SELECT current_database(), current_user, current_setting('server_version')"
)

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

POSTGRES_QUERY_SH = r"""
db="$1"
sql="$2"
user="${POSTGRES_USER:-postgres}"
if [ -n "${POSTGRES_PASSWORD:-}" ]; then
  PGPASSWORD="$POSTGRES_PASSWORD"
  export PGPASSWORD
elif [ -n "${POSTGRES_PASSWORD_FILE:-}" ] && [ -f "$POSTGRES_PASSWORD_FILE" ]; then
  PGPASSWORD=$(cat "$POSTGRES_PASSWORD_FILE")
  export PGPASSWORD
fi
if ! command -v psql >/dev/null 2>&1; then
  echo "psql was not found in the database container" >&2
  exit 127
fi
psql -U "$user" -d "$db" -tAc "$sql"
"""

POSTGRES_DUMP_SH = r"""
db="$1"
user="${POSTGRES_USER:-postgres}"
if [ -n "${POSTGRES_PASSWORD:-}" ]; then
  PGPASSWORD="$POSTGRES_PASSWORD"
  export PGPASSWORD
elif [ -n "${POSTGRES_PASSWORD_FILE:-}" ] && [ -f "$POSTGRES_PASSWORD_FILE" ]; then
  PGPASSWORD=$(cat "$POSTGRES_PASSWORD_FILE")
  export PGPASSWORD
fi
if ! command -v pg_dump >/dev/null 2>&1; then
  echo "pg_dump was not found in the database container" >&2
  exit 127
fi
pg_dump -U "$user" --format=plain --no-owner --no-acl "$db"
"""

POSTGRES_CAPABILITY_SH = r"""
db="$1"
user="${POSTGRES_USER:-postgres}"
if [ -n "${POSTGRES_PASSWORD:-}" ]; then
  PGPASSWORD="$POSTGRES_PASSWORD"
  export PGPASSWORD
elif [ -n "${POSTGRES_PASSWORD_FILE:-}" ] && [ -f "$POSTGRES_PASSWORD_FILE" ]; then
  PGPASSWORD=$(cat "$POSTGRES_PASSWORD_FILE")
  export PGPASSWORD
fi
if ! command -v psql >/dev/null 2>&1; then
  echo "psql was not found in the database container" >&2
  exit 127
fi
if ! command -v pg_dump >/dev/null 2>&1; then
  echo "pg_dump was not found in the database container" >&2
  exit 127
fi
echo "PSQL=$(command -v psql)"
echo "PG_DUMP=$(command -v pg_dump)"
echo "PG_DUMPALL=$(command -v pg_dumpall 2>/dev/null || true)"
echo "PG_USER=$user"
psql -U "$user" -d "$db" -tAc "SELECT 1" >/dev/null || exit 1
echo "PG_META=$(psql -U "$user" -d "$db" -tAc "SELECT current_database() || '|' || current_user || '|' || current_setting('server_version')")"
pg_dump -U "$user" --schema-only --format=plain "$db" | awk "NR<=8 {print}"
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
    parsed["dump_method"] = f"docker exec {container} mysqldump --single-transaction --databases {database}"
    parsed["engine"] = "MariaDB"
    return parsed


def parse_docker_db_entry(entry: object) -> tuple[str, str]:
    """Return (container, engine) from a docker_databases mapping value."""
    if isinstance(entry, dict):
        container = str(entry.get("container") or "").strip().lstrip("/")
        engine = str(entry.get("engine") or "MariaDB")
        return container, engine
    return str(entry or "").strip().lstrip("/"), "MariaDB"


def is_postgres_engine(engine: str) -> bool:
    return "postgres" in str(engine or "").lower()


def docker_postgres_argv(container: str, database: str, sql: str) -> list[str]:
    safe_container = require_docker_name(container)
    db_name = _safe_db_name(database)
    statement = str(sql or "").strip()
    key = statement.upper()
    if key == "SELECT 1":
        actual = "SELECT 1"
    elif key in {"SIZE_AND_TABLES", "SELECT PG_DATABASE_SIZE"}:
        actual = PG_SIZE_SQL
    elif key in {"SCHEMA_LIST", "SHOW TABLES"}:
        actual = PG_SCHEMA_SQL
    elif key == "META":
        actual = PG_META_SQL
    else:
        raise ValueError(f"Refusing unsafe SQL for container fingerprint: {sql!r}")
    return [
        "docker",
        "exec",
        safe_container,
        "sh",
        "-c",
        POSTGRES_QUERY_SH,
        "serverbackup-psql",
        db_name,
        actual,
    ]


def docker_pg_dump_argv(container: str, database: str) -> list[str]:
    safe_container = require_docker_name(container)
    db_name = _safe_db_name(database)
    return [
        "docker",
        "exec",
        safe_container,
        "sh",
        "-c",
        POSTGRES_DUMP_SH,
        "serverbackup-pgdump",
        db_name,
    ]


def docker_pg_capability_argv(container: str, database: str) -> list[str]:
    safe_container = require_docker_name(container)
    db_name = _safe_db_name(database)
    return [
        "docker",
        "exec",
        safe_container,
        "sh",
        "-c",
        POSTGRES_CAPABILITY_SH,
        "serverbackup-pgcap",
        db_name,
    ]


def parse_pg_size(stdout: str) -> dict[str, int]:
    text = (stdout or "").strip().splitlines()
    if not text:
        return {"size_bytes": 0, "table_count": 0, "row_count": 0}
    parts = [p.strip() for p in text[0].replace("|", " ").split() if p.strip()]
    size = table_count = rows = 0
    try:
        size = int(parts[0]) if parts else 0
    except ValueError:
        size = 0
    try:
        table_count = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        table_count = 0
    try:
        rows = int(float(parts[2])) if len(parts) > 2 else 0
    except ValueError:
        rows = 0
    return {"size_bytes": size, "table_count": table_count, "row_count": rows}


def docker_postgres_schema_details(run, container: str, database: str) -> dict:
    """Read-only size/table probe inside a PostgreSQL container. Never uses mysql."""
    try:
        result = run(docker_postgres_argv(container, database, "SIZE_AND_TABLES"), timeout=30)
    except Exception as exc:  # noqa: BLE001
        return {
            "size_bytes": None,
            "table_count": None,
            "row_count": None,
            "probe": f"PostgreSQL size probe failed: {exc}",
            "dump_capable": False,
            "engine": "PostgreSQL",
        }
    code = getattr(result, "returncode", 1)
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    if code != 0:
        detail = (stderr or stdout or "docker exec psql failed").strip().splitlines()
        safe = detail[0][:200] if detail else "docker exec psql failed"
        return {
            "size_bytes": None,
            "table_count": None,
            "row_count": None,
            "probe": safe,
            "dump_capable": False,
            "engine": "PostgreSQL",
        }
    parsed = parse_pg_size(stdout)
    cap_ok = False
    cap_detail = ""
    tools: dict[str, str] = {}
    meta = {"database": database, "user": "", "version": ""}
    try:
        cap = run(docker_pg_capability_argv(container, database), timeout=30)
        cap_out = (getattr(cap, "stdout", "") or "") + "\n" + (getattr(cap, "stderr", "") or "")
        for line in cap_out.splitlines():
            if line.startswith("PSQL="):
                tools["psql"] = line.split("=", 1)[1].strip()
            elif line.startswith("PG_DUMP="):
                tools["pg_dump"] = line.split("=", 1)[1].strip()
            elif line.startswith("PG_DUMPALL="):
                tools["pg_dumpall"] = line.split("=", 1)[1].strip()
            elif line.startswith("PG_USER="):
                meta["user"] = line.split("=", 1)[1].strip()
            elif line.startswith("PG_META="):
                parts = line.split("=", 1)[1].strip().split("|")
                if parts:
                    meta["database"] = parts[0].strip() or database
                if len(parts) > 1:
                    meta["user"] = parts[1].strip() or meta["user"]
                if len(parts) > 2:
                    meta["version"] = parts[2].strip()
        cap_ok = getattr(cap, "returncode", 1) == 0 and "PostgreSQL database dump" in cap_out
        if getattr(cap, "returncode", 1) != 0:
            cap_detail = (getattr(cap, "stderr", "") or cap_out).strip().splitlines()
            cap_detail = cap_detail[0][:200] if cap_detail else "pg_dump capability failed"
        elif not cap_ok:
            cap_detail = "pg_dump ran but output was not a PostgreSQL dump header"
    except Exception as exc:  # noqa: BLE001
        cap_detail = str(exc)
    parsed["probe"] = "pg_database_size via docker exec psql succeeded (read-only; full dump not stored)"
    parsed["dump_capable"] = bool(cap_ok)
    parsed["dump_probe"] = (
        "pg_dump --schema-only produced a PostgreSQL dump header (discarded; Dry Run does not keep a dump)"
        if cap_ok
        else cap_detail
    )
    parsed["engine"] = "PostgreSQL"
    parsed["postgres_user"] = meta["user"] or "POSTGRES_USER inside container"
    parsed["postgres_version"] = meta["version"]
    parsed["database_name"] = meta["database"] or database
    parsed["tools"] = tools
    parsed["dump_method"] = (
        f"docker exec {container} pg_dump -U $POSTGRES_USER --format=plain --no-owner --no-acl {database}"
    )
    return parsed


def docker_schema_details_for(run, container: str, database: str, engine: str = "") -> dict:
    if is_postgres_engine(engine):
        return docker_postgres_schema_details(run, container, database)
    return docker_schema_details(run, container, database)


def docker_dump_argv_for(container: str, database: str, engine: str = "") -> list[str]:
    if is_postgres_engine(engine):
        return docker_pg_dump_argv(container, database)
    return docker_dump_argv(container, database)
