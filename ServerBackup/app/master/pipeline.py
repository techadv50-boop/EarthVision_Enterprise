"""Master backup pipeline used by BACKUP NOW, DRY RUN, and REBUILD MASTER."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
import json
import struct

from app import __version__
from app.backup.live import (
    BackupLiveSession,
    STAGE_COMPLETE,
    STAGE_DISCOVERY,
    STAGE_DUMPING,
    STAGE_DUMP_PREPARING,
    STAGE_FAILED,
    STAGE_FINGERPRINT,
    STAGE_TRANSFERRING,
    STAGE_UNCHANGED,
    STAGE_VERIFYING,
    UI_COMMITTING,
    UI_CONNECTING,
    UI_DATABASE,
    UI_DISCOVERING,
    UI_FAILED,
    UI_HASHING,
    UI_INVENTORY,
    UI_PREPARING,
    UI_SUCCESS,
    UI_TRANSFERRING,
    UI_VERIFYING,
    application_for_root,
    log_pipeline,
)
from app.config.schema import SYSTEM_DATABASES
from app.database.discover import discover_databases
from app.discover.engine import DiscoveryError as ApplicationDiscoveryError
from app.discover.engine import discover_applications
from app.discover.gate import assess_backup_gate, backup_gate_error, format_backup_gate
from app.discover.report import format_application_sections
from app.master.delta import compute_delta, next_tree_files, promote_unhashed_for_preview
from app.master.health import HEALTHY, WARNING, assess_health
from app.master.pack import unpack_to_objects
from app.master.store import MasterStore
from app.master.tree import file_key
from app.ojs.discover import DiscoveryError, is_required_ojs_application, validate_discovery
from app.ssh.client import SSHError
from app.ssh.timeouts import SSHCommandTimeout
from app.utils.disk import drive_status
from app.utils.format import format_bytes

POSTGRES_SYSTEM_DATABASES = frozenset({"template0", "template1", "postgres"})

BLOCKED_PREFIXES = (
    "/var/lib/containerd",
    "/var/lib/docker",
    "/srv/namecheap-migration",
    "/home/zhzh/server-migration-backup",
)


class PipelineError(RuntimeError):
    pass


def _json_script(
    engine,
    action: str,
    extra: dict[str, Any] | None = None,
    *,
    timeout: int | None = None,
    require_ok: bool = True,
) -> dict[str, Any]:
    payload = engine._payload(action, extra)
    live = getattr(engine, "live", None)
    if live is not None:
        live.ssh_action = action
        live.publish()
    result = engine.ssh.run_script(engine.config.remote_prepare_script, payload, timeout=timeout)
    parsed = engine._parse_json_result(result.stdout)
    if not result.ok and not parsed:
        raise PipelineError(result.stderr.strip() or result.stdout.strip() or f"{action} failed")
    if require_ok and parsed.get("ok") is False:
        raise PipelineError(str(parsed.get("error") or result.stderr.strip() or f"{action} failed"))
    return parsed


def _is_blocked(path: str, extra: list[str]) -> bool:
    cleaned = path.rstrip("/")
    extras = {item.rstrip("/") for item in extra}
    if cleaned in extras:
        return False
    return any(cleaned == prefix or cleaned.startswith(prefix + "/") for prefix in BLOCKED_PREFIXES)


def collect_sources(config, ojs_installs: list[dict[str, Any]]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    extra = list(config.extra_directories or [])
    seen: set[str] = set()

    def add(path: str, category: str) -> None:
        cleaned = path.rstrip("/")
        if cleaned in seen:
            return
        seen.add(cleaned)
        sources.append({"root": cleaned, "category": category})

    for path in config.website_directories:
        if _is_blocked(path, extra):
            raise PipelineError(f"Refusing blocked source {path}")
        add(path, "website")
    for install in ojs_installs:
        root = str(install.get("files_dir") or "")
        if not root:
            raise PipelineError("OJS installation is missing files_dir")
        if _is_blocked(root, extra):
            raise PipelineError(f"Refusing blocked OJS files_dir {root}")
        add(root, "ojs")
    nginx = config.nginx_directory
    if nginx:
        add(nginx, "nginx")
    for path in extra:
        if _is_blocked(path, extra):
            continue
        add(path, "extra")
    return sources


def collect_sources_from_applications(config, applications: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Filesystem sources from Nginx discovery. Skips excluded/removed/docker-internal paths."""
    sources: list[dict[str, str]] = []
    extra = list(config.extra_directories or [])
    seen: set[str] = set()

    def add(path: str, category: str) -> None:
        cleaned = (path or "").rstrip("/")
        if not cleaned or cleaned in seen:
            return
        if cleaned.startswith("volume:"):
            return
        if _is_blocked(cleaned, extra):
            return
        seen.add(cleaned)
        sources.append({"root": cleaned, "category": category})

    for app in applications:
        if app.get("change") == "removed" or app.get("excluded"):
            continue
        files_dir = str(app.get("ojs_files_dir") or "").rstrip("/")
        for path in app.get("source_paths") or []:
            category = "ojs" if files_dir and str(path).rstrip("/") == files_dir else "website"
            add(str(path), category)
        if files_dir:
            add(files_dir, "ojs")
    nginx = config.nginx_directory
    if nginx:
        add(nginx, "nginx")
    for path in extra:
        if _is_blocked(path, extra):
            continue
        add(path, "extra")
    return sources


def applications_to_ojs(applications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    installs: list[dict[str, Any]] = []
    for app in applications:
        if app.get("type") != "OJS" or app.get("change") == "removed":
            continue
        installs.append(
            {
                "domain": (app.get("hostnames") or [app.get("hostname")])[0] if (app.get("hostnames") or app.get("hostname")) else app.get("hostname"),
                "application_path": app.get("root"),
                "files_dir": app.get("ojs_files_dir") or "",
                "size_bytes": int(app.get("estimated_bytes") or 0),
                "exists": bool(app.get("ojs_files_dir")),
            }
        )
    return installs


def merge_discovered_databases(
    config,
    discovery: dict[str, Any],
    mysql_names: list[str],
) -> tuple[list[str], list[str]]:
    mariadb: list[str] = []
    postgres: list[str] = []

    def add_maria(name: str) -> None:
        cleaned = str(name or "").strip()
        if not cleaned:
            return
        if config.exclude_system_databases and cleaned in SYSTEM_DATABASES:
            return
        if cleaned not in mariadb:
            mariadb.append(cleaned)

    def add_pg(name: str) -> None:
        cleaned = str(name or "").strip()
        if not cleaned:
            return
        if cleaned in POSTGRES_SYSTEM_DATABASES:
            return
        if cleaned not in postgres:
            postgres.append(cleaned)

    dbs = discovery.get("databases") if isinstance(discovery.get("databases"), dict) else {}
    for name in dbs.get("mariadb") or []:
        add_maria(str(name))
    for name in dbs.get("postgresql") or []:
        add_pg(str(name))
    for name in mysql_names:
        add_maria(str(name))
    for app in discovery.get("applications") or []:
        if app.get("change") == "removed":
            continue
        dtype = str(app.get("database_type") or "")
        dname = str(app.get("database_name") or "")
        if dtype == "PostgreSQL":
            add_pg(dname)
        elif dname:
            add_maria(dname)
    return mariadb, postgres


def _required_roots(sources: list[dict[str, str]]) -> list[str]:
    return [item["root"].rstrip("/") for item in sources]


def _discover_ojs(engine) -> list[dict[str, Any]]:
    parsed = _json_script(engine, "discover-ojs")
    return validate_discovery(parsed, website_directories=engine.config.website_directories)


def _inventory(engine, sources: list[dict[str, str]]) -> list[dict[str, Any]]:
    parsed = _json_script(engine, "inventory", {"sources": sources}, timeout=engine.config.transfer_timeout)
    files = parsed.get("files") if isinstance(parsed, dict) else None
    if not isinstance(files, list):
        raise PipelineError("Inventory returned no file list.")
    if parsed.get("ok") is False:
        raise PipelineError("; ".join(parsed.get("errors") or ["inventory failed"]))
    return files


def _inventory_preview(engine, sources: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    """DRY RUN inventory. Missing optional roots are warnings, not a hard failure."""
    if not sources:
        return [], []
    parsed = _json_script(
        engine,
        "inventory",
        {"sources": sources},
        timeout=engine.config.transfer_timeout,
        require_ok=False,
    )
    files = parsed.get("files") if isinstance(parsed, dict) else None
    if not isinstance(files, list):
        raise PipelineError("Inventory returned no file list.")
    errors = [str(item) for item in (parsed.get("errors") or [])]
    return files, errors


def _hash_paths(engine, paths: list[str], allowed_roots: list[str]) -> dict[str, str]:
    if not paths:
        return {}
    parsed = _json_script(
        engine,
        "hash-files",
        {"paths": paths, "allowed_roots": allowed_roots},
        timeout=engine.config.transfer_timeout,
    )
    mapping: dict[str, str] = {}
    for item in parsed.get("hashes") or []:
        mapping[str(item.get("path"))] = str(item.get("sha256") or "").lower()
    if parsed.get("ok") is False:
        raise PipelineError("; ".join(parsed.get("errors") or ["hash-files failed"]))
    return mapping


def _stream_files(
    engine,
    store: MasterStore,
    files: list[dict[str, Any]],
    allowed_roots: list[str],
    live: BackupLiveSession | None = None,
    *,
    transfer_kind: str = "files",
    database_name: str = "",
    db_type: str = "MariaDB",
) -> int:
    if not files:
        return 0
    payload_files = []
    by_abs = {}
    for item in files:
        path = item.get("absolute_path") or f"{item.get('source_root')}/{item.get('relative_path')}"
        payload_files.append({"path": path, "absolute_path": path})
        by_abs[str(path)] = item
    total_bytes = int(sum(int(item.get("size") or 0) for item in files))
    if live is not None and transfer_kind == "files":
        live.set_file_totals(files_total=len(files), bytes_total=total_bytes)

    def on_progress(info: dict[str, Any]) -> None:
        if live is None:
            return
        if transfer_kind == "database" and database_name:
            live.database_event(
                name=database_name,
                db_type=db_type,
                stage=STAGE_TRANSFERRING,
                status="Transferring dump to Windows…",
                bytes_transferred=int(info.get("bytes_done") or 0),
                bytes_total=total_bytes,
                bytes_produced=total_bytes,
            )
            return
        key = str(info.get("key") or "")
        rec = by_abs.get(key)
        root = str((rec or {}).get("source_root") or "")
        live.file_progress(
            files_done=int(info.get("files_done") or 0),
            objects_done=int(info.get("objects_done") or 0),
            bytes_done=int(info.get("bytes_done") or 0),
            source_root=root,
            current_object=key,
        )

    process = engine.ssh.popen_script(
        engine.config.remote_prepare_script,
        {
            "action": "stream-objects",
            "files": payload_files,
            "allowed_roots": allowed_roots,
        },
    )
    stdout = process.stdout
    if stdout is None:
        raise PipelineError("Object stream has no stdout.")
    if live is not None:
        live.set_ui_stage(UI_TRANSFERRING, "Transferring changed objects…", phase="transferring")
        live.ssh_action = "stream-objects"
        live.publish()
    try:
        stored = unpack_to_objects(
            stdout,
            store.staging_dir,
            lambda tmp, expected: _put_object(store, tmp, expected, live=live),
            should_cancel=engine.progress.cancel_requested,
            on_progress=on_progress if live is not None else None,
        )
    except (SSHCommandTimeout, SSHError, ValueError, struct.error, OSError) as exc:
        killer = getattr(process, "kill", None)
        if callable(killer):
            try:
                killer()
            except Exception:
                pass
        if "cancelled" in str(exc).lower():
            raise
        raise PipelineError(str(exc)) from exc
    code = process.wait()
    if code not in (0, None):
        stderr = b""
        if getattr(process, "stderr", None):
            stderr = process.stderr.read() or b""
        raise PipelineError(stderr.decode("utf-8", "replace") or f"stream-objects exit {code}")
    transferred = 0
    for item in stored:
        transferred += int(item.get("size") or 0)
        key = str(item.get("key") or "")
        rec = by_abs.get(key)
        if rec is not None:
            rec["sha256"] = str(item.get("sha256"))
    missing = [path for path, rec in by_abs.items() if not rec.get("sha256")]
    if missing:
        raise PipelineError("Interrupted object transfer; missing: " + ", ".join(missing[:8]))
    if live is not None and transfer_kind != "database":
        live.overall["file_bytes_complete"] = transferred
        live.overall["files_done"] = len(stored)
        live.overall["objects_done"] = len(stored)
        live.overall["bytes_done"] = transferred
        live.publish(phase="transferring", message="Transfer complete.")
    return transferred


def _put_object(store: MasterStore, tmp, expected, live: BackupLiveSession | None = None):
    size = 0
    try:
        size = int(tmp.stat().st_size) if tmp.is_file() else 0
    except OSError:
        size = 0
    digest = store.put_file_object(tmp, expected=expected)
    if live is not None:
        live.note_master_write(size)
    return digest


def _iter_ndjson(stdout) -> Iterator[dict[str, Any]]:
    while True:
        raw = stdout.readline()
        if not raw:
            break
        if isinstance(raw, bytes):
            text = raw.decode("utf-8", "replace").strip()
        else:
            text = str(raw).strip()
        if not text:
            continue
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def _apply_dump_event(live: BackupLiveSession | None, event: dict[str, Any]) -> None:
    if live is None:
        return
    stage = str(event.get("stage") or "")
    name = str(event.get("name") or "")
    if stage == STAGE_DISCOVERY:
        estimates: dict[str, int] = {}
        for item in event.get("databases") or []:
            if isinstance(item, dict) and item.get("name"):
                estimates[str(item["name"])] = int(item.get("estimated_bytes") or 0)
        if estimates:
            live.apply_dump_estimates(estimates)
        first = next(iter(estimates), name)
        live.database_event(
            name=first or name,
            stage=STAGE_DISCOVERY,
            status=str(event.get("status") or "Measuring schema sizes…"),
            db_type=str(event.get("type") or "MariaDB"),
            bytes_estimated=estimates.get(first) if first else None,
        )
        return
    if not stage and not name:
        return
    live.database_event(
        name=name or str(live.database.get("name") or ""),
        stage=stage or STAGE_DUMPING,
        status=str(event.get("status") or "running"),
        db_type=str(event.get("type") or "MariaDB"),
        bytes_produced=event.get("bytes_produced"),
        bytes_estimated=event.get("estimated_bytes"),
        bytes_transferred=event.get("bytes_written") if stage == STAGE_TRANSFERRING else None,
        elapsed_seconds=event.get("elapsed_seconds"),
        error=str(event.get("error") or ""),
    )


def _consume_dump_progress(process, live: BackupLiveSession | None) -> list[dict[str, Any]]:
    dumps: list[dict[str, Any]] = []
    stdout = process.stdout
    if stdout is None:
        raise PipelineError("dump-databases has no stdout.")
    error = ""
    failed = False
    for event in _iter_ndjson(stdout):
        if event.get("event") == "ok" or (event.get("ok") is True and event.get("dumps") is not None):
            dumps = list(event.get("dumps") or [])
            continue
        if event.get("ok") is False and event.get("event") != "progress":
            error = str(event.get("error") or error or "dump-databases failed")
            failed = True
            _apply_dump_event(
                live,
                {
                    "stage": STAGE_FAILED,
                    "name": event.get("name") or (live.database.get("name") if live else ""),
                    "status": "failed",
                    "error": error,
                    "type": event.get("type") or "MariaDB",
                },
            )
            continue
        _apply_dump_event(live, event)
        if str(event.get("stage") or "") == STAGE_FAILED:
            failed = True
            error = str(event.get("error") or error or "mysqldump failed")
    code = process.wait()
    stderr = b""
    if getattr(process, "stderr", None):
        stderr = process.stderr.read() or b""
    if isinstance(stderr, bytes):
        stderr_text = stderr.decode("utf-8", "replace").strip()
    else:
        stderr_text = str(stderr).strip()
    if failed or code not in (0, None) or not dumps:
        raise PipelineError(error or stderr_text or f"dump-databases exit {code}")
    return dumps


def _fingerprint_databases(engine, names: list[str] | None = None) -> dict[str, str]:
    names = list(names if names is not None else engine.config.databases_for_backup())
    if not names:
        return {}
    parsed = _json_script(engine, "database-fingerprint", {"databases": names})
    mapping = {}
    for item in parsed.get("fingerprints") or []:
        mapping[str(item.get("name"))] = str(item.get("sha256") or "")
    if parsed.get("ok") is False:
        raise PipelineError("; ".join(parsed.get("errors") or ["database fingerprint failed"]))
    missing = [name for name in names if name not in mapping]
    if missing:
        raise PipelineError("Database fingerprint missing for: " + ", ".join(missing))
    return mapping


def _dump_changed_databases(
    engine,
    store: MasterStore,
    changed: list[str],
    allowed_roots: list[str],
    live: BackupLiveSession | None = None,
) -> dict[str, str]:
    if not changed:
        return {}
    if live is not None:
        live.overall["objects_total"] = int(live.overall.get("files_total") or 0) + len(changed)
        for name in changed:
            live.database_event(
                name=name,
                stage=STAGE_DUMP_PREPARING,
                status="Preparing mysqldump…",
                db_type="MariaDB",
            )
    process = engine.ssh.popen_script(
        engine.config.remote_prepare_script,
        engine._payload(
            "dump-databases",
            {
                "databases": changed,
                "work_id": engine.backup_id.replace("_", ""),
                "compression_level": engine.config.compression_level,
            },
        ),
    )
    if live is not None:
        live.ssh_action = "dump-databases"
        live.publish()
    try:
        dumps = _consume_dump_progress(process, live)
    except (SSHCommandTimeout, SSHError, PipelineError) as exc:
        killer = getattr(process, "kill", None)
        if callable(killer):
            try:
                killer()
            except Exception:
                pass
        if isinstance(exc, PipelineError):
            if live is not None and live.database.get("stage") != STAGE_FAILED:
                live.database_event(
                    name=changed[0],
                    stage=STAGE_FAILED,
                    status="failed",
                    error="dump-databases failed",
                )
            raise
        raise PipelineError(str(exc)) from exc
    result: dict[str, str] = {}
    for item in dumps:
        name = str(item.get("name"))
        files = [
            {
                "absolute_path": item["path"],
                "source_root": "/tmp",
                "relative_path": Path(item["path"]).name,
                "size": item.get("size") or 0,
            }
        ]
        if live is not None:
            live.database_event(
                name=name,
                stage=STAGE_TRANSFERRING,
                status="Transferring dump to Windows…",
                db_type="MariaDB",
                bytes_produced=int(item.get("size") or 0),
                bytes_transferred=0,
                bytes_total=int(item.get("size") or 0),
            )
        _stream_files(
            engine,
            store,
            files,
            allowed_roots + ["/tmp"],
            live=live,
            transfer_kind="database",
            database_name=name,
            db_type="MariaDB",
        )
        rec = files[0]
        if live is not None:
            live.database_event(
                name=name,
                stage=STAGE_VERIFYING,
                status="Verifying stored dump object…",
                db_type="MariaDB",
                bytes_produced=int(item.get("size") or 0),
                bytes_transferred=int(item.get("size") or 0),
                bytes_total=int(item.get("size") or 0),
            )
        if not rec.get("sha256"):
            if live is not None:
                live.database_event(
                    name=name,
                    stage=STAGE_FAILED,
                    status="failed",
                    error=f"Database dump for {name} was not stored.",
                )
            raise PipelineError(f"Database dump for {name} was not stored.")
        result[name] = str(rec["sha256"])
        if live is not None:
            live.database_event(
                name=name,
                stage=STAGE_COMPLETE,
                status="Dump stored.",
                db_type="MariaDB",
                bytes_produced=int(item.get("size") or 0),
                bytes_transferred=int(item.get("size") or 0),
                bytes_total=int(item.get("size") or 0),
            )
    return result


def _absolute(item: dict[str, Any]) -> str:
    if item.get("absolute_path"):
        return str(item["absolute_path"])
    rel = str(item.get("relative_path") or "").lstrip("/")
    root = str(item.get("source_root") or "").rstrip("/")
    return f"{root}/{rel}" if rel else root


def _key_hashes(inventory: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in inventory:
        digest = str(item.get("sha256") or "").lower()
        if digest:
            mapping[file_key(str(item.get("source_root") or ""), str(item.get("relative_path") or ""))] = digest
    return mapping


def _apply_abs_hashes(inventory: list[dict[str, Any]], abs_hashes: dict[str, str]) -> None:
    for item in inventory:
        digest = abs_hashes.get(_absolute(item))
        if digest:
            item["sha256"] = digest


def format_dry_run_report(
    *,
    has_master: bool,
    generation: int | None,
    op_type: str,
    ojs: list[dict[str, Any]],
    sources: list[dict[str, str]],
    db_names: list[str],
    db_result: str,
    db_error: str = "",
    changed_dbs: list[str] | None = None,
    counts: dict[str, int] | None = None,
    estimated_bytes: int = 0,
    applications: list[dict[str, Any]] | None = None,
    postgres_names: list[str] | None = None,
    db_discovery_error: str = "",
    full_baseline_bytes: int = 0,
    inventory_warnings: list[str] | None = None,
    nginx_inventory: list[dict[str, Any]] | None = None,
    parsed_hostnames: list[str] | None = None,
    database_inventory: list[dict[str, Any]] | None = None,
    inactive_hostnames: list[dict[str, Any]] | None = None,
    gate: dict[str, Any] | None = None,
    database_account: dict[str, Any] | None = None,
) -> str:
    """Human-readable DRY RUN summary. Never mutates master or HEAD."""
    changed_dbs = list(changed_dbs or [])
    counts = counts or {}
    applications = list(applications or [])
    postgres_names = list(postgres_names or [])
    inventory_warnings = list(inventory_warnings or [])
    if not has_master:
        master_status = "NO BASELINE"
        mode = "FULL BASELINE PREVIEW"
        expected = "FULL MASTER BASELINE"
    elif op_type == "NO_CHANGE":
        master_status = f"GENERATION {generation}"
        mode = "NO_CHANGE PREVIEW"
        expected = "NO_CHANGE"
    else:
        master_status = f"GENERATION {generation}"
        mode = "INCREMENTAL PREVIEW"
        expected = "INCREMENTAL"
    ojs_lines = [
        f"  {item.get('application_path') or item.get('domain')} -> {item.get('files_dir')}"
        for item in ojs
    ] or ["  (none discovered)"]
    db_map = {"mariadb": list(db_names or []), "postgresql": list(postgres_names or [])}
    if applications:
        app_header = format_application_sections(
            applications,
            databases=db_map,
            nginx_inventory=nginx_inventory,
            parsed_hostnames=parsed_hostnames,
            database_inventory=database_inventory,
            inactive_hostnames=inactive_hostnames,
            gate=gate,
            database_account=database_account,
        )
    else:
        websites = [item["root"] for item in sources if item.get("category") == "website"]
        web_lines = [f"  {path}" for path in websites] or ["  (none)"]
        app_header = ["WEBSITES:", *web_lines]
    if db_error:
        db_line = f"fingerprint failed: {db_error}"
    elif db_discovery_error and not db_names and not postgres_names:
        db_line = f"discovery failed: {db_discovery_error}"
    elif not db_names and not postgres_names:
        db_line = "none discovered"
    elif not has_master:
        db_line = "discovered"
    elif db_result == "UNCHANGED":
        db_line = "unchanged"
    elif changed_dbs:
        db_line = "changed (" + ", ".join(changed_dbs) + ")"
    else:
        db_line = db_result.lower()
    db_detail = [
        f"  MariaDB: {', '.join(db_names) if db_names else '(none discovered)'}",
        f"  PostgreSQL: {', '.join(postgres_names) if postgres_names else '(none discovered)'}",
    ]
    if db_discovery_error and (db_names or postgres_names):
        db_detail.append(f"  discovery warning: {db_discovery_error}")
    counts_line = (
        f"NEW={counts.get('new', 0)} MODIFIED={counts.get('modified', 0)} "
        f"DELETED={counts.get('deleted', 0)} RENAMED={counts.get('renamed', 0)} "
        f"MOVED={counts.get('moved', 0)}"
    )
    warning_lines = [f"  {item}" for item in inventory_warnings] if inventory_warnings else []
    return "\n".join(
        [
            f"MASTER STATUS: {master_status}",
            f"MODE: {mode}",
            *app_header,
            *(["OJS FILES_DIR:", *ojs_lines] if not applications else []),
            f"DATABASES: {db_line}",
            *(db_detail if not applications else []),
            f"EXPECTED ACTION: {expected}",
            f"EXPECTED FULL BASELINE SIZE: {format_bytes(full_baseline_bytes or estimated_bytes)}",
            f"ESTIMATED TRANSFER: {format_bytes(estimated_bytes)}",
            "HEAD: unchanged",
            counts_line,
            *(["INVENTORY WARNINGS:", *warning_lines] if warning_lines else []),
        ]
    )


def _dry_run_stage(engine, token: str, message: str, pct: int) -> None:
    engine.logger.info(token)
    engine.progress.write(
        status="running",
        phase="dry-run",
        backup_id=engine.backup_id,
        message=message,
        bytes_done=pct,
        bytes_total=100,
    )


def _run_dry_run_preview(engine, store: MasterStore) -> dict[str, Any]:
    """Server-wide read-only discovery + metadata inventory. Does not write HEAD or run BACKUP NOW."""
    config = engine.config
    _dry_run_stage(engine, "DRY_RUN_DISCOVERY_START", "Discovering Nginx applications…", 30)
    try:
        discovery = discover_applications(config, ssh=engine.ssh, persist=True)
    except ApplicationDiscoveryError as exc:
        engine.logger.error(f"DRY_RUN_ERROR application discovery: {exc}")
        raise PipelineError(str(exc)) from exc
    applications = list(discovery.get("applications") or [])
    if not discovery.get("nginx_ok") and not applications:
        error = "; ".join(discovery.get("errors") or ["Nginx application discovery failed"])
        engine.logger.error(f"DRY_RUN_ERROR {error}")
        raise PipelineError(error)
    for app in applications:
        names = [str(n) for n in (app.get("hostnames") or []) if n] or [str(app.get("hostname") or "")]
        engine.logger.info(
            "DISCOVERED_APPLICATION "
            f"{app.get('application_id')} hostnames={','.join(names)} "
            f"root={app.get('root') or '-'} db={app.get('database_name') or '-'}"
        )
        for name in names:
            if name:
                engine.logger.info(f"DISCOVERED_HOSTNAME {name} application={app.get('application_id')}")
    for name in discovery.get("parsed_hostnames") or []:
        engine.logger.info(f"NGINX_SERVER_NAME {name}")
    for row in discovery.get("database_inventory") or []:
        engine.logger.info(
            "DISCOVERED_DATABASE "
            f"{row.get('name')} status={row.get('status')} application={row.get('application_id') or '-'}"
        )
    for row in discovery.get("inactive_hostnames") or []:
        engine.logger.info(
            "INACTIVE_HOSTNAME "
            f"{row.get('hostname')} verdict={row.get('verdict')}"
        )
    engine.logger.info(" ".join(format_backup_gate(discovery.get("backup_gate") or {})))
    _dry_run_stage(engine, "DRY_RUN_DISCOVERY_COMPLETE", "Application discovery complete.", 40)
    ojs = applications_to_ojs(applications)
    for install in ojs:
        engine.logger.info(
            f"{install.get('domain')} files_dir={install.get('files_dir')} "
            f"size={(install.get('size_bytes') or 0) / (1024**3):.1f} GB"
        )
    sources = collect_sources_from_applications(config, applications)
    _dry_run_stage(engine, "DRY_RUN_INVENTORY_START", "Building file inventory…", 50)
    inventory, inventory_warnings = _inventory_preview(engine, sources)
    for warning in inventory_warnings:
        engine.logger.info(f"DRY_RUN_INVENTORY_WARNING {warning}")
    _dry_run_stage(engine, "DRY_RUN_INVENTORY_COMPLETE", "Inventory complete.", 70)
    previous = store.load_tree() if store.has_head() else {"files": []}
    has_master = store.has_head()
    op_type = "FULL" if not has_master else "INCREMENTAL"
    engine._check_cancel()
    hashes = _key_hashes(inventory)
    _dry_run_stage(engine, "DRY_RUN_DELTA_START", "Comparing inventory to master…", 75)
    changes = compute_delta(previous if has_master else None, inventory, hashes=hashes)
    promote_unhashed_for_preview(changes)
    _dry_run_stage(engine, "DRY_RUN_DELTA_COMPLETE", "Delta preview complete.", 85)

    mysql_names: list[str] = []
    db_discovery_error = ""
    try:
        rows = discover_databases(config, client=engine.ssh)
        mysql_names = [str(row.get("name") or "") for row in rows if isinstance(row, dict)]
    except Exception as exc:  # noqa: BLE001
        db_discovery_error = str(exc)
        engine.logger.error(f"DRY_RUN_ERROR database discovery: {exc}")
    mariadb_names, postgres_names = merge_discovered_databases(config, discovery, mysql_names)

    db_names = mariadb_names
    db_result = "SKIPPED"
    db_error = ""
    fingerprints: dict[str, str] = {}
    changed_dbs: list[str] = []
    if db_names:
        _dry_run_stage(engine, "DRY_RUN_DB_FINGERPRINT_START", "Fingerprinting MariaDB databases…", 90)
        try:
            fingerprints = _fingerprint_databases(engine, db_names)
            previous_fp = (store.load_meta().get("database_fingerprints") or {}) if has_master else {}
            for name in db_names:
                if fingerprints.get(name) != previous_fp.get(name):
                    changed_dbs.append(name)
            db_result = "UNCHANGED" if not changed_dbs else "CHANGED"
            _dry_run_stage(engine, "DRY_RUN_DB_FINGERPRINT_COMPLETE", "Database fingerprint complete.", 95)
        except Exception as exc:  # noqa: BLE001
            db_result = "FAILED"
            db_error = str(exc)
            engine.logger.error(f"DRY_RUN_ERROR database fingerprint: {exc}")
            engine.logger.info("DRY_RUN_DB_FINGERPRINT_COMPLETE")
    elif postgres_names:
        db_result = "DISCOVERED"
        _dry_run_stage(engine, "DRY_RUN_DB_FINGERPRINT_START", "PostgreSQL discovered; MariaDB fingerprint skipped.", 90)
        _dry_run_stage(engine, "DRY_RUN_DB_FINGERPRINT_COMPLETE", "Database discovery complete.", 95)
    else:
        db_result = "NONE"
        _dry_run_stage(engine, "DRY_RUN_DB_FINGERPRINT_START", "No MariaDB databases discovered.", 90)
        _dry_run_stage(engine, "DRY_RUN_DB_FINGERPRINT_COMPLETE", "Database discovery complete.", 95)

    counts = changes.counts()
    engine.logger.info(
        f"Change detection: NEW={counts['new']} MODIFIED={counts['modified']} "
        f"DELETED={counts['deleted']} RENAMED={counts['renamed']} MOVED={counts['moved']}"
    )
    discovered_bytes = int(
        sum(int(app.get("estimated_bytes") or 0) for app in applications if app.get("change") != "removed")
    )
    inventory_bytes = int(sum(int(item.get("size") or 0) for item in inventory))
    transfer_bytes = int(changes.estimated_transfer_bytes())
    full_baseline_bytes = max(inventory_bytes, discovered_bytes, transfer_bytes if not has_master else 0)
    preview_type = (
        "NO_CHANGE"
        if has_master and changes.empty and not changed_dbs and not db_error
        else op_type
    )
    report_ok = not db_error
    report_text = format_dry_run_report(
        has_master=has_master,
        generation=store.head_generation(),
        op_type=preview_type,
        ojs=ojs,
        sources=sources,
        db_names=db_names,
        db_result=db_result,
        db_error=db_error,
        changed_dbs=changed_dbs,
        counts=counts,
        estimated_bytes=transfer_bytes,
        applications=applications,
        postgres_names=postgres_names,
        db_discovery_error=db_discovery_error,
        full_baseline_bytes=full_baseline_bytes,
        inventory_warnings=inventory_warnings,
        nginx_inventory=list(discovery.get("nginx_inventory") or discovery.get("servers") or []),
        parsed_hostnames=list(discovery.get("parsed_hostnames") or []),
        database_inventory=list(discovery.get("database_inventory") or []),
        inactive_hostnames=list(discovery.get("inactive_hostnames") or []),
        gate=discovery.get("backup_gate") or assess_backup_gate(applications, list(discovery.get("database_inventory") or [])),
        database_account=discovery.get("database_account") or {},
    )
    try:
        dest = Path(config.backup_destination)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "dry-run-last.txt").write_text(report_text, encoding="utf-8")
    except OSError:
        pass
    report = {
        "ok": report_ok,
        "operation": "DRY_RUN",
        "type": preview_type,
        "master_exists": has_master,
        "counts": counts,
        "estimated_transfer_bytes": transfer_bytes,
        "full_baseline_bytes": full_baseline_bytes,
        "database": db_result,
        "changed_databases": changed_dbs,
        "databases": {"mariadb": db_names, "postgresql": postgres_names},
        "applications": applications,
        "ojs": ojs,
        "sources": sources,
        "report_text": report_text,
        "hashed": False,
        "head_unchanged": True,
        "error": db_error or None,
    }
    engine.logger.info("DRY_RUN_RESULT")
    engine.progress.write(
        status="success" if report_ok else "failed",
        message="Dry run complete. HEAD unchanged." if report_ok else db_error,
        dry_run=report,
        bytes_done=100,
        bytes_total=100,
    )
    return report


def run_master_backup(engine, *, rebuild: bool = False, dry_run: bool = False) -> dict[str, Any]:
    config = engine.config
    store = MasterStore(config.backup_destination)
    op_id = engine.backup_id.replace("_", "")
    started = datetime.now()
    timestamp = started.strftime("%Y-%m-%d %H:%M:%S")
    if not dry_run:
        engine.progress.write(status="running", phase="master", backup_id=engine.backup_id, message="Master backup…")
    dest = Path(config.backup_destination)
    drive = drive_status(dest)
    if not drive.exists:
        raise PipelineError(drive.error or "Backup drive is unavailable.")
    if drive.free_gb < config.min_free_disk_gb:
        raise PipelineError("Insufficient disk space.")

    if dry_run:
        engine.progress.write(phase="ssh", ui_stage=UI_CONNECTING, message="Connecting to Ubuntu…")

        def _login_dry() -> None:
            result = engine.ssh.test_login()
            if not result.ok:
                raise SSHError(result.stderr.strip() or "SSH login failed.")

        engine._retry("SSH connectivity", _login_dry)
        engine.progress.write(phase="helpers", ui_stage=UI_PREPARING, message="Installing Ubuntu backup helpers…")
        helpers = engine.ssh.ensure_remote_scripts()
        if not helpers.ok:
            raise PipelineError(helpers.stderr.strip() or "Could not install Ubuntu backup helpers.")
        engine._check_cancel()
        return _run_dry_run_preview(engine, store)

    live = getattr(engine, "live", None)
    if live is None:
        live = BackupLiveSession(
            engine.progress,
            operation="BACKUP",
            backup_id=engine.backup_id,
        )
        engine.live = live
    log_pipeline(engine, "BACKUP_START", engine.backup_id)
    live.set_ui_stage(UI_PREPARING, "Master backup…", phase="master")

    log_pipeline(engine, "SSH_CONNECT_START")
    live.set_ui_stage(UI_CONNECTING, "Connecting to Ubuntu…", phase="ssh")

    def _login() -> None:
        result = engine.ssh.test_login()
        if not result.ok:
            raise SSHError(result.stderr.strip() or "SSH login failed.")

    engine._retry("SSH connectivity", _login)
    log_pipeline(engine, "SSH_CONNECTED")
    live.set_ui_stage(UI_PREPARING, "Installing Ubuntu backup helpers…", phase="helpers")
    helpers = engine.ssh.ensure_remote_scripts()
    if not helpers.ok:
        raise PipelineError(helpers.stderr.strip() or "Could not install Ubuntu backup helpers.")

    engine._check_cancel()

    log_pipeline(engine, "REMOTE_DISCOVERY_START")
    live.set_ui_stage(UI_DISCOVERING, "Discovering applications…", phase="discovery")
    try:
        discovery = discover_applications(config, ssh=engine.ssh, persist=True)
    except ApplicationDiscoveryError as exc:
        raise PipelineError(str(exc)) from exc
    applications = list(discovery.get("applications") or [])
    live.applications = applications
    live.operation = "BACKUP"
    live.publish(phase="discovery", message="Discovering applications…")
    log_pipeline(engine, "REMOTE_DISCOVERY_COMPLETE", f"applications={len(applications)}")
    gate = discovery.get("backup_gate") or assess_backup_gate(
        list(discovery.get("applications") or []),
        list(discovery.get("database_inventory") or []),
    )
    engine.logger.info(" ".join(format_backup_gate(gate)))
    if gate.get("block_complete_backup"):
        raise PipelineError(backup_gate_error(gate))

    engine.logger.info("OJS discovery started")
    try:
        ojs = _discover_ojs(engine)
    except DiscoveryError as exc:
        raise PipelineError(str(exc)) from exc
    for install in ojs:
        engine.logger.info(
            f"{install.get('domain')} files_dir={install.get('files_dir')} "
            f"size={(install.get('size_bytes') or 0) / (1024**3):.1f} GB"
        )
    required_missing = [
        path
        for path in config.website_directories
        if is_required_ojs_application(path) and not any(
            str(item.get("application_path") or "").rstrip("/") == path.rstrip("/") for item in ojs
        )
    ]
    if required_missing:
        raise PipelineError("Required OJS application(s) were not discovered: " + ", ".join(required_missing))

    sources = collect_sources(config, ojs)
    log_pipeline(engine, "INVENTORY_START")
    if sources:
        live.current_source = str(sources[0].get("root") or "")
        live.application = application_for_root(live.applications, live.current_source)
    live.set_ui_stage(UI_INVENTORY, "Building file inventory…", phase="inventory")
    inventory = _inventory(engine, sources)
    log_pipeline(engine, "INVENTORY_COMPLETE", f"files={len(inventory)}")
    live.overall["files_total"] = len(inventory)
    live.overall["objects_total"] = len(inventory)
    live.publish(phase="inventory", message=f"Inventory complete ({len(inventory)} files).")
    previous = store.load_tree() if store.has_head() and not rebuild else {"files": []}
    has_master = store.has_head() and not rebuild
    op_type = "FULL" if not has_master or rebuild else "INCREMENTAL"
    live.operation = "BACKUP — FULL MASTER BASELINE" if op_type == "FULL" else "BACKUP — INCREMENTAL"
    live.publish()

    engine._check_cancel()
    hashes = _key_hashes(inventory)
    changes = compute_delta(previous if has_master else None, inventory, hashes=hashes)
    log_pipeline(engine, "DELTA_COMPLETE")
    if changes.hash_candidates:
        log_pipeline(engine, "HASH_START")
        live.set_ui_stage(UI_HASHING, "Hashing changed file candidates…", phase="hash")
        paths = [_absolute(item) for item in changes.hash_candidates]
        abs_hashes = _hash_paths(engine, paths, _required_roots(sources))
        _apply_abs_hashes(inventory, abs_hashes)
        hashes = _key_hashes(inventory)
        changes = compute_delta(previous if has_master else None, inventory, hashes=hashes)
        log_pipeline(engine, "HASH_COMPLETE")

    db_names = config.databases_for_backup()
    db_result = "SKIPPED"
    fingerprints: dict[str, str] = {}
    changed_dbs: list[str] = []
    if db_names:
        log_pipeline(engine, "DATABASE_FINGERPRINT_START")
        live.set_ui_stage(UI_DATABASE, "Fingerprinting MariaDB databases…", phase="database")
        live.database_event(
            name=db_names[0],
            stage=STAGE_DISCOVERY,
            status="Listing selected databases…",
            db_type="MariaDB",
        )
        for name in db_names:
            live.database_event(
                name=name,
                stage=STAGE_FINGERPRINT,
                status="Comparing database fingerprints…",
                db_type="MariaDB",
            )
        try:
            fingerprints = _fingerprint_databases(engine)
            previous_fp = (store.load_meta().get("database_fingerprints") or {}) if has_master else {}
            for name in db_names:
                if fingerprints.get(name) != previous_fp.get(name):
                    changed_dbs.append(name)
                else:
                    live.database_event(
                        name=name,
                        stage=STAGE_UNCHANGED,
                        status="Fingerprint matches; dump skipped.",
                        db_type="MariaDB",
                    )
            db_result = "UNCHANGED" if not changed_dbs else "CHANGED"
            log_pipeline(
                engine,
                "DATABASE_FINGERPRINT_COMPLETE",
                f"changed={len(changed_dbs)} unchanged={len(db_names) - len(changed_dbs)}",
            )
        except Exception as exc:  # noqa: BLE001
            live.database_event(
                name=db_names[0],
                stage=STAGE_FAILED,
                status="failed",
                error=str(exc),
            )
            raise PipelineError(f"Database backup failed: {exc}") from exc

    counts = changes.counts()
    engine.logger.info(
        f"Change detection: NEW={counts['new']} MODIFIED={counts['modified']} "
        f"DELETED={counts['deleted']} RENAMED={counts['renamed']} MOVED={counts['moved']}"
    )

    no_change = has_master and changes.empty and not changed_dbs and not rebuild
    if no_change:
        history = {
            "operation_id": op_id,
            "timestamp": timestamp,
            "type": "NO_CHANGE",
            "status": "SUCCESS",
            "generation": store.head_generation(),
            "bytes_transferred": 0,
            "database": "UNCHANGED",
            "integrity": "OK",
            **counts,
        }
        store.write_history_only(history)
        live.set_ui_stage(UI_SUCCESS, "NO CHANGES DETECTED", phase="complete")
        live.finish("success", UI_SUCCESS, "NO CHANGES DETECTED", staging_state="NONE")
        engine.logger.info("NO_CHANGE Master already current")
        return {
            "status": "SUCCESS",
            "type": "NO_CHANGE",
            "generation": store.head_generation(),
            "bytes_transferred": 0,
            "counts": counts,
            "database": "UNCHANGED",
            "ojs": ojs,
            "history": history,
        }

    previous_head = store.head_generation()
    store.begin_staging(op_id)
    transferred = 0
    db_objects: dict[str, str] = {}
    committed = False
    try:
        engine._check_cancel()
        to_send = list(changes.transfer)
        if op_type == "FULL":
            to_send = [item for item in inventory]
        log_pipeline(engine, "OBJECT_TRANSFER_START", f"files={len(to_send)}")
        live.set_ui_stage(UI_TRANSFERRING, "Transferring changed objects…", phase="transferring")
        transferred = _stream_files(engine, store, to_send, _required_roots(sources), live=live)
        log_pipeline(engine, "OBJECT_TRANSFER_COMPLETE", f"bytes={transferred}")
        hashes = _key_hashes(inventory)
        changes = compute_delta(previous if has_master else None, inventory, hashes=hashes)

        if db_names and changed_dbs:
            log_pipeline(engine, "DATABASE_DUMP_START", ",".join(changed_dbs))
            live.set_ui_stage(UI_DATABASE, "Dumping changed MariaDB databases…", phase="database")
            try:
                db_objects = _dump_changed_databases(
                    engine,
                    store,
                    changed_dbs,
                    _required_roots(sources),
                    live=live,
                )
                db_result = "OK"
                log_pipeline(engine, "DATABASE_DUMP_COMPLETE")
            except Exception as exc:  # noqa: BLE001
                raise PipelineError(f"Database backup failed: {exc}") from exc
        elif db_names:
            db_objects = dict(store.load_meta().get("database_objects") or {})
            db_result = "UNCHANGED"

        engine._check_cancel()
        log_pipeline(engine, "VERIFY_START")
        live.set_ui_stage(UI_VERIFYING, "Verifying transferred objects…", phase="verify")
        generation = 1 if previous_head is None else int(previous_head) + 1
        files = next_tree_files(changes, generation=generation, timestamp=timestamp)
        inventory_keys = {
            file_key(str(item.get("source_root") or ""), str(item.get("relative_path") or ""))
            for item in inventory
        }
        tree_keys = {
            file_key(str(item.get("source_root") or ""), str(item.get("relative_path") or ""))
            for item in files
        }
        missing_files = sorted(inventory_keys - tree_keys)
        extra_files = sorted(tree_keys - inventory_keys)
        if missing_files or extra_files:
            raise PipelineError(
                "Tree completeness check failed: missing "
                + ", ".join(missing_files[:8] or ["(none)"])
                + "; extra "
                + ", ".join(extra_files[:8] or ["(none)"])
            )
        tree = {
            "generation": generation,
            "timestamp": timestamp,
            "files": files,
            "ojs": ojs,
            "sources": sources,
            "databases": db_names,
            "database_objects": db_objects,
        }
        for rec in files:
            digest = rec.get("sha256")
            if not digest or not store.object_exists(str(digest)):
                raise PipelineError(f"Missing object for {rec.get('source_root')}/{rec.get('relative_path')}")
        if db_names:
            for name in db_names:
                digest = db_objects.get(name)
                if not digest or not store.object_exists(str(digest)):
                    raise PipelineError(f"Missing database object for {name}")

        source_bytes = int(sum(int(item.get("size") or 0) for item in files))
        meta = {
            "format": 1,
            "master_id": store.load_meta().get("master_id") or op_id,
            "status": HEALTHY,
            "created_at": store.load_meta().get("created_at") or timestamp,
            "updated_at": timestamp,
            "generation": generation,
            "server_ip": config.server_ip,
            "hostname": None,
            "app_version": __version__,
            "sources": sources,
            "ojs": ojs,
            "source_bytes": source_bytes,
            "master_bytes": source_bytes,
            "integrity": "OK",
            "database": db_result,
            "database_fingerprints": fingerprints or store.load_meta().get("database_fingerprints") or {},
            "database_objects": db_objects,
        }
        history = {
            "operation_id": op_id,
            "timestamp": timestamp,
            "type": "FULL" if op_type == "FULL" else "INCREMENTAL",
            "status": "SUCCESS",
            "generation": generation,
            "bytes_transferred": transferred,
            "database": db_result,
            "integrity": "OK",
            "duration_seconds": int((datetime.now() - started).total_seconds()),
            **changes.counts(),
        }
        if not files:
            raise PipelineError("Refusing to commit an empty master tree.")
        log_pipeline(engine, "VERIFY_COMPLETE")
        log_pipeline(engine, "HEAD_COMMIT_START")
        live.set_ui_stage(UI_COMMITTING, "Committing HEAD…", phase="commit")
        store.commit(generation=generation, tree=tree, meta=meta, history=history)
        committed = True
        if store.head_generation() != generation:
            raise PipelineError("HEAD did not advance after commit.")
        log_pipeline(engine, "HEAD_COMMIT_COMPLETE", f"generation={generation}")
        live.set_committed(int(live.master.get("write_bytes") or transferred or 0), generation=generation)
        live.head_state = str(generation)
        health = assess_health(
            store,
            required_sources=None,
            require_database=bool(db_names),
            deep=False,
        )
        log_pipeline(engine, "BACKUP_SUCCESS")
        live.finish("success", UI_SUCCESS, "MASTER BACKUP STATUS=SUCCESS", staging_state="CLEANED")
        engine.logger.info("Master update committed")
        return {
            "status": "SUCCESS",
            "type": history["type"],
            "generation": generation,
            "bytes_transferred": transferred,
            "counts": changes.counts(),
            "database": db_result,
            "ojs": ojs,
            "health": health,
            "previous_head": previous_head,
        }
    finally:
        if not committed:
            # Existing HEAD must remain the previous generation.
            current = store.head_generation()
            if current != previous_head:
                engine.logger.error(f"HEAD changed during failed operation ({previous_head} -> {current})")
            live.head_state = "UNCHANGED"
            live.staging_state = "CLEANED"
        store.cleanup_staging(op_id)
        try:
            engine.ssh.run_script(
                config.remote_prepare_script,
                {"action": "cleanup", "work_id": engine.backup_id.replace("_", "")},
                timeout=120,
            )
        except Exception:
            pass
