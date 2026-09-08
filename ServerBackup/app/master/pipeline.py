"""Master backup pipeline used by BACKUP NOW, DRY RUN, and REBUILD MASTER."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import struct

from app import __version__
from app.master.delta import compute_delta, next_tree_files, promote_unhashed_for_preview
from app.master.health import HEALTHY, WARNING, assess_health
from app.master.pack import unpack_to_objects
from app.master.store import MasterStore
from app.master.tree import file_key
from app.ojs.discover import DiscoveryError, is_required_ojs_application, validate_discovery
from app.ssh.client import SSHError
from app.utils.disk import drive_status
from app.utils.format import format_bytes

BLOCKED_PREFIXES = (
    "/var/lib/containerd",
    "/var/lib/docker",
    "/srv/namecheap-migration",
    "/home/zhzh/server-migration-backup",
)


class PipelineError(RuntimeError):
    pass


def _json_script(engine, action: str, extra: dict[str, Any] | None = None, *, timeout: int = 120) -> dict[str, Any]:
    payload = engine._payload(action, extra)
    result = engine.ssh.run_script(engine.config.remote_prepare_script, payload, timeout=timeout)
    parsed = engine._parse_json_result(result.stdout)
    if not result.ok and not parsed:
        raise PipelineError(result.stderr.strip() or result.stdout.strip() or f"{action} failed")
    if parsed.get("ok") is False:
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


def _required_roots(sources: list[dict[str, str]]) -> list[str]:
    return [item["root"].rstrip("/") for item in sources]


def _discover_ojs(engine) -> list[dict[str, Any]]:
    parsed = _json_script(engine, "discover-ojs", timeout=120)
    return validate_discovery(parsed, website_directories=engine.config.website_directories)


def _inventory(engine, sources: list[dict[str, str]]) -> list[dict[str, Any]]:
    parsed = _json_script(engine, "inventory", {"sources": sources}, timeout=engine.config.transfer_timeout)
    files = parsed.get("files") if isinstance(parsed, dict) else None
    if not isinstance(files, list):
        raise PipelineError("Inventory returned no file list.")
    if parsed.get("ok") is False:
        raise PipelineError("; ".join(parsed.get("errors") or ["inventory failed"]))
    return files


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


def _stream_files(engine, store: MasterStore, files: list[dict[str, Any]], allowed_roots: list[str]) -> int:
    if not files:
        return 0
    payload_files = []
    for item in files:
        path = item.get("absolute_path") or f"{item.get('source_root')}/{item.get('relative_path')}"
        payload_files.append({"path": path, "absolute_path": path})
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
    by_abs = {}
    for item in files:
        path = str(item.get("absolute_path") or f"{item.get('source_root')}/{item.get('relative_path')}")
        by_abs[path] = item
    try:
        stored = unpack_to_objects(
            stdout,
            store.staging_dir,
            lambda tmp, expected: store.put_file_object(tmp, expected=expected),
            should_cancel=engine.progress.cancel_requested,
        )
    except (ValueError, struct.error, OSError) as exc:
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
    return transferred


def _fingerprint_databases(engine) -> dict[str, str]:
    names = engine.config.databases_for_backup()
    if not names:
        return {}
    parsed = _json_script(engine, "database-fingerprint", {"databases": names}, timeout=120)
    mapping = {}
    for item in parsed.get("fingerprints") or []:
        mapping[str(item.get("name"))] = str(item.get("sha256") or "")
    if parsed.get("ok") is False:
        raise PipelineError("; ".join(parsed.get("errors") or ["database fingerprint failed"]))
    missing = [name for name in names if name not in mapping]
    if missing:
        raise PipelineError("Database fingerprint missing for: " + ", ".join(missing))
    return mapping


def _dump_changed_databases(engine, store: MasterStore, changed: list[str], allowed_roots: list[str]) -> dict[str, str]:
    if not changed:
        return {}
    parsed = _json_script(
        engine,
        "dump-databases",
        {
            "databases": changed,
            "work_id": engine.backup_id.replace("_", ""),
            "compression_level": engine.config.compression_level,
        },
        timeout=engine.config.transfer_timeout,
    )
    dumps = parsed.get("dumps") or []
    files = [
        {
            "absolute_path": item["path"],
            "source_root": "/tmp",
            "relative_path": Path(item["path"]).name,
            "size": item.get("size") or 0,
        }
        for item in dumps
    ]
    _stream_files(engine, store, files, allowed_roots + ["/tmp"])
    result = {}
    for item in dumps:
        name = str(item.get("name"))
        rec = next((row for row in files if row["absolute_path"] == item["path"]), None)
        if not rec or not rec.get("sha256"):
            raise PipelineError(f"Database dump for {name} was not stored.")
        result[name] = str(rec["sha256"])
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
) -> str:
    """Human-readable DRY RUN summary. Never mutates master or HEAD."""
    changed_dbs = list(changed_dbs or [])
    counts = counts or {}
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
    websites = [item["root"] for item in sources if item.get("category") == "website"]
    web_lines = [f"  {path}" for path in websites] or ["  (none)"]
    if db_error:
        db_line = f"fingerprint failed: {db_error}"
    elif not db_names:
        db_line = "none configured"
    elif not has_master:
        db_line = "discovered"
    elif db_result == "UNCHANGED":
        db_line = "unchanged"
    elif changed_dbs:
        db_line = "changed (" + ", ".join(changed_dbs) + ")"
    else:
        db_line = db_result.lower()
    counts_line = (
        f"NEW={counts.get('new', 0)} MODIFIED={counts.get('modified', 0)} "
        f"DELETED={counts.get('deleted', 0)} RENAMED={counts.get('renamed', 0)} "
        f"MOVED={counts.get('moved', 0)}"
    )
    return "\n".join(
        [
            f"MASTER STATUS: {master_status}",
            f"MODE: {mode}",
            "OJS:",
            *ojs_lines,
            "WEBSITES:",
            *web_lines,
            f"DATABASES: {db_line}",
            f"EXPECTED ACTION: {expected}",
            f"ESTIMATED TRANSFER: {format_bytes(estimated_bytes)}",
            "HEAD: unchanged",
            counts_line,
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

    engine.progress.write(phase="ssh", message="Connecting to Ubuntu…")

    def _login() -> None:
        result = engine.ssh.test_login()
        if not result.ok:
            raise SSHError(result.stderr.strip() or "SSH login failed.")

    engine._retry("SSH connectivity", _login)
    helpers = engine.ssh.ensure_remote_scripts()
    if not helpers.ok:
        raise PipelineError(helpers.stderr.strip() or "Could not install Ubuntu backup helpers.")

    engine._check_cancel()
    if dry_run:
        _dry_run_stage(engine, "DRY_RUN_DISCOVERY_START", "Discovering OJS files_dir…", 30)
    else:
        engine.logger.info("OJS discovery started")
    try:
        ojs = _discover_ojs(engine)
    except DiscoveryError as exc:
        if dry_run:
            engine.logger.error(f"DRY_RUN_ERROR OJS discovery: {exc}")
        raise PipelineError(str(exc)) from exc
    if dry_run:
        _dry_run_stage(engine, "DRY_RUN_DISCOVERY_COMPLETE", "OJS discovery complete.", 40)
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
    if dry_run:
        _dry_run_stage(engine, "DRY_RUN_INVENTORY_START", "Building file inventory…", 50)
    else:
        engine.progress.write(phase="inventory", message="Building file inventory…")
    inventory = _inventory(engine, sources)
    if dry_run:
        _dry_run_stage(engine, "DRY_RUN_INVENTORY_COMPLETE", "Inventory complete.", 70)
    previous = store.load_tree() if store.has_head() and not rebuild else {"files": []}
    has_master = store.has_head() and not rebuild
    op_type = "FULL" if not has_master or rebuild else "INCREMENTAL"

    engine._check_cancel()
    hashes = _key_hashes(inventory)
    if dry_run:
        _dry_run_stage(engine, "DRY_RUN_DELTA_START", "Comparing inventory to master…", 75)
    changes = compute_delta(previous if has_master else None, inventory, hashes=hashes)
    if dry_run:
        # Metadata-only preview. Hashing the live tree (including ~19 GB OJS)
        # is what made first-run DRY RUN appear frozen at 0%.
        promote_unhashed_for_preview(changes)
        _dry_run_stage(engine, "DRY_RUN_DELTA_COMPLETE", "Delta preview complete.", 85)
    elif changes.hash_candidates:
        engine.progress.write(phase="hash", message="Hashing changed file candidates…")
        paths = [_absolute(item) for item in changes.hash_candidates]
        abs_hashes = _hash_paths(engine, paths, _required_roots(sources))
        _apply_abs_hashes(inventory, abs_hashes)
        hashes = _key_hashes(inventory)
        changes = compute_delta(previous if has_master else None, inventory, hashes=hashes)

    db_names = config.databases_for_backup()
    db_result = "SKIPPED"
    db_error = ""
    fingerprints: dict[str, str] = {}
    changed_dbs: list[str] = []
    if db_names:
        if dry_run:
            _dry_run_stage(engine, "DRY_RUN_DB_FINGERPRINT_START", "Fingerprinting MariaDB databases…", 90)
        else:
            engine.progress.write(phase="database", message="Fingerprinting MariaDB databases…")
        try:
            fingerprints = _fingerprint_databases(engine)
            previous_fp = (store.load_meta().get("database_fingerprints") or {}) if has_master else {}
            for name in db_names:
                if fingerprints.get(name) != previous_fp.get(name):
                    changed_dbs.append(name)
            db_result = "UNCHANGED" if not changed_dbs else "CHANGED"
            if dry_run:
                _dry_run_stage(engine, "DRY_RUN_DB_FINGERPRINT_COMPLETE", "Database fingerprint complete.", 95)
        except Exception as exc:  # noqa: BLE001
            if dry_run:
                db_result = "FAILED"
                db_error = str(exc)
                engine.logger.error(f"DRY_RUN_ERROR database fingerprint: {exc}")
                engine.logger.info("DRY_RUN_DB_FINGERPRINT_COMPLETE")
            else:
                raise PipelineError(f"Database backup failed: {exc}") from exc

    counts = changes.counts()
    engine.logger.info(
        f"Change detection: NEW={counts['new']} MODIFIED={counts['modified']} "
        f"DELETED={counts['deleted']} RENAMED={counts['renamed']} MOVED={counts['moved']}"
    )

    if dry_run:
        preview_type = (
            "NO_CHANGE"
            if has_master and changes.empty and not changed_dbs and not db_error and not rebuild
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
            estimated_bytes=changes.estimated_transfer_bytes(),
        )
        report = {
            "ok": report_ok,
            "operation": "DRY_RUN",
            "type": preview_type,
            "master_exists": has_master,
            "counts": counts,
            "estimated_transfer_bytes": changes.estimated_transfer_bytes(),
            "database": db_result,
            "changed_databases": changed_dbs,
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
        engine.progress.write(status="success", phase="complete", message="NO CHANGES DETECTED")
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
        engine.progress.write(phase="transferring", message="Transferring changed objects…")
        transferred = _stream_files(engine, store, to_send, _required_roots(sources))
        hashes = _key_hashes(inventory)
        changes = compute_delta(previous if has_master else None, inventory, hashes=hashes)

        if db_names and changed_dbs:
            engine.progress.write(phase="database", message="Dumping changed MariaDB databases…")
            try:
                db_objects = _dump_changed_databases(engine, store, changed_dbs, _required_roots(sources))
                db_result = "OK"
            except Exception as exc:  # noqa: BLE001
                raise PipelineError(f"Database backup failed: {exc}") from exc
        elif db_names:
            db_objects = dict(store.load_meta().get("database_objects") or {})
            db_result = "UNCHANGED"

        engine._check_cancel()
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
        store.commit(generation=generation, tree=tree, meta=meta, history=history)
        committed = True
        if store.head_generation() != generation:
            raise PipelineError("HEAD did not advance after commit.")
        health = assess_health(
            store,
            required_sources=None,
            require_database=bool(db_names),
            deep=False,
        )
        engine.progress.write(status="success", phase="complete", message="MASTER BACKUP STATUS=SUCCESS")
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
        store.cleanup_staging(op_id)
        try:
            engine.ssh.run_script(
                config.remote_prepare_script,
                {"action": "cleanup", "work_id": engine.backup_id.replace("_", "")},
                timeout=120,
            )
        except Exception:
            pass
