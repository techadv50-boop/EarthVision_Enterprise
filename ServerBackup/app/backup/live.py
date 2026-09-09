"""Live backup progress. Percentages are omitted unless both sides are measured."""

from __future__ import annotations

import time
from typing import Any, Mapping

from app.utils.format import format_bytes, format_hms

STAGE_DISCOVERY = "DATABASE DISCOVERY"
STAGE_FINGERPRINT = "DATABASE FINGERPRINT"
STAGE_UNCHANGED = "DATABASE UNCHANGED"
STAGE_DUMP_PREPARING = "DATABASE DUMP PREPARING"
STAGE_DUMPING = "DATABASE DUMPING"
STAGE_TRANSFERRING = "DATABASE TRANSFERRING"
STAGE_VERIFYING = "DATABASE VERIFYING"
STAGE_COMPLETE = "DATABASE COMPLETE"
STAGE_FAILED = "DATABASE FAILED"

PREPARING_STAGES = frozenset({STAGE_DISCOVERY, STAGE_FINGERPRINT, STAGE_DUMP_PREPARING})
MEASURING_STAGES = frozenset({STAGE_DUMPING, STAGE_TRANSFERRING, STAGE_VERIFYING})

UI_PREPARING = "PREPARING"
UI_CONNECTING = "CONNECTING"
UI_DISCOVERING = "DISCOVERING"
UI_INVENTORY = "INVENTORY"
UI_HASHING = "HASHING"
UI_DATABASE = "DATABASE"
UI_TRANSFERRING = "TRANSFERRING"
UI_VERIFYING = "VERIFYING"
UI_COMMITTING = "COMMITTING"
UI_SUCCESS = "SUCCESS"
UI_FAILED = "FAILED"
UI_CANCELLED = "CANCELLED"

UI_STAGES = (
    UI_PREPARING,
    UI_CONNECTING,
    UI_DISCOVERING,
    UI_INVENTORY,
    UI_HASHING,
    UI_DATABASE,
    UI_TRANSFERRING,
    UI_VERIFYING,
    UI_COMMITTING,
    UI_SUCCESS,
    UI_FAILED,
    UI_CANCELLED,
)

SCANNING_UI = frozenset({UI_PREPARING, UI_CONNECTING, UI_DISCOVERING, UI_INVENTORY, UI_HASHING})

PHASE_TO_STAGE = {
    "ssh": UI_CONNECTING,
    "lock": UI_PREPARING,
    "storage": UI_PREPARING,
    "helpers": UI_PREPARING,
    "master": UI_PREPARING,
    "discovery": UI_DISCOVERING,
    "discover": UI_DISCOVERING,
    "inventory": UI_INVENTORY,
    "hash": UI_HASHING,
    "database": UI_DATABASE,
    "transferring": UI_TRANSFERRING,
    "transfer": UI_TRANSFERRING,
    "verify": UI_VERIFYING,
    "commit": UI_COMMITTING,
}


def friendly_stage(ui_stage: str, progress: Mapping[str, Any] | None = None) -> str:
    """Human Stage line. Never leave a generic 'ssh' label on a later pipeline step."""
    data = dict(progress or {})
    status = str(data.get("status") or "").lower()
    last = str(data.get("last_stage") or "")
    phase = str(data.get("phase") or "")
    raw = str(ui_stage or "")
    if status in {"failed", "cancelled"} and last and last not in {UI_FAILED, UI_CANCELLED, UI_SUCCESS, ""}:
        raw = last
    elif raw in {"", UI_FAILED, UI_CANCELLED} and last and last not in {UI_FAILED, UI_CANCELLED, UI_SUCCESS}:
        raw = last
    if raw.lower() == "ssh" or phase == "ssh" and raw in {"", UI_PREPARING}:
        raw = UI_CONNECTING
    if raw.lower() == "ssh":
        raw = UI_CONNECTING
    mapped = PHASE_TO_STAGE.get(raw.lower())
    if mapped:
        raw = mapped
    if raw == UI_TRANSFERRING:
        return "OBJECT TRANSFER"
    return raw or PHASE_TO_STAGE.get(phase, phase.upper() if phase else "—")


def log_pipeline(engine, token: str, detail: str = "") -> None:
    """Log a real pipeline state token. Never include secrets."""
    line = token if not detail else f"{token} {detail}"
    logger = getattr(engine, "logger", None)
    if logger is not None:
        logger.info(line)


def is_backup_operation(progress: Mapping[str, Any] | None) -> bool:
    data = dict(progress or {})
    operation = str(data.get("operation") or "")
    if operation.upper().startswith("BACKUP"):
        return True
    return bool(data.get("ui_stage"))


def show_live_backup_panel(
    progress: Mapping[str, Any] | None,
    *,
    running: bool,
    backup_active: bool = False,
) -> bool:
    """Keep the live panel visible for the whole BACKUP NOW lifecycle, including failure."""
    if running or backup_active:
        return True
    data = dict(progress or {})
    status = str(data.get("status") or "").lower()
    if status in {"running", "failed", "cancelled", "success"} and is_backup_operation(data):
        return True
    return False


def measurable_percent(
    done: int | float | None,
    total: int | float | None,
    *,
    stage: str = "",
) -> float | None:
    """Return 0-100.0 only when both values are real and total > 0. Never invent a percent."""
    if done is None or total is None:
        return None
    try:
        done_n = float(done)
        total_n = float(total)
    except (TypeError, ValueError):
        return None
    if total_n <= 0 or done_n < 0:
        return None
    if done_n > total_n:
        if stage == STAGE_DUMPING:
            return 99.9
        return None
    percent = round(done_n * 100.0 / total_n, 1)
    if percent >= 100 and stage == STAGE_DUMPING:
        return 99.9
    return min(100.0, percent)


def progress_label(*, done: int | None, total: int | None, stage: str = "", ui_stage: str = "") -> str:
    ui = str(ui_stage or "")
    if (done is None or int(done) == 0) and (total is None or int(total) <= 0):
        if ui == UI_INVENTORY:
            return "Scanning..."
        if ui == UI_VERIFYING:
            return "Verifying..."
        if ui == UI_TRANSFERRING or stage in MEASURING_STAGES:
            return "Calculating..."
        if ui in SCANNING_UI or stage in PREPARING_STAGES or not stage:
            return "Preparing..."
        return "Preparing..."
    if stage in PREPARING_STAGES or (not done and stage == STAGE_DUMPING and not total):
        if stage == STAGE_DUMPING:
            return "Calculating..."
        return "Preparing..."
    if done is None or done < 0:
        if stage in MEASURING_STAGES or ui == UI_TRANSFERRING:
            return "Calculating..."
        if ui == UI_VERIFYING:
            return "Verifying..."
        return "Preparing..."
    if total is None or total <= 0:
        return f"{format_bytes(done)} produced"
    if done > total:
        return f"{format_bytes(done)} produced"
    return f"{format_bytes(done)} / {format_bytes(total)}"


def eta_seconds(*, done: int | None, total: int | None, speed_bps: float | None) -> int | None:
    if not speed_bps or speed_bps <= 0:
        return None
    if done is None or total is None or total <= 0 or done < 0:
        return None
    remaining = int(total) - int(done)
    if remaining <= 0:
        return 0
    return int(remaining / speed_bps)


def speed_label(speed_bps: float | int | None) -> str:
    if not speed_bps or speed_bps <= 0:
        return "—"
    return f"{format_bytes(speed_bps)}/s"


def application_for_database(applications: list[dict[str, Any]] | None, name: str) -> str:
    wanted = str(name or "")
    for app in applications or []:
        if str(app.get("database_name") or "") == wanted:
            hosts = [str(n) for n in (app.get("hostnames") or []) if n]
            return str(app.get("hostname") or (hosts[0] if hosts else "") or app.get("root") or "")
    return ""


def application_for_root(applications: list[dict[str, Any]] | None, root: str) -> str:
    cleaned = str(root or "").rstrip("/")
    for app in applications or []:
        app_root = str(app.get("root") or "").rstrip("/")
        files_dir = str(app.get("ojs_files_dir") or "").rstrip("/")
        if cleaned and cleaned in {app_root, files_dir}:
            hosts = [str(n) for n in (app.get("hostnames") or []) if n]
            return str(app.get("hostname") or (hosts[0] if hosts else "") or app_root)
        if app_root and (cleaned == app_root or cleaned.startswith(app_root + "/")):
            hosts = [str(n) for n in (app.get("hostnames") or []) if n]
            return str(app.get("hostname") or (hosts[0] if hosts else "") or app_root)
    if cleaned:
        return cleaned.rsplit("/", 1)[-1]
    return ""


def format_live_backup_panel(progress: Mapping[str, Any] | None, *, now: float | None = None) -> str:
    """Human-readable BACKUP NOW panel. Omits percentages that were not measured."""
    data = dict(progress or {})
    operation = str(data.get("operation") or data.get("message") or "BACKUP")
    db = data.get("database") if isinstance(data.get("database"), dict) else {}
    overall = data.get("overall") if isinstance(data.get("overall"), dict) else {}
    master = data.get("master") if isinstance(data.get("master"), dict) else {}
    ui_stage = str(data.get("ui_stage") or "")
    started = data.get("started_at")
    elapsed = data.get("elapsed_seconds")
    if now is not None and started:
        try:
            elapsed = max(0, int(now - float(started)))
        except (TypeError, ValueError):
            elapsed = elapsed
    percent = overall.get("percent")
    if percent is None:
        percent = measurable_percent(
            overall.get("bytes_done"),
            overall.get("bytes_total"),
            stage=str(db.get("stage") or data.get("phase") or ""),
        )
    if percent is None:
        overall_line = str(
            overall.get("label")
            or progress_label(
                done=overall.get("bytes_done"),
                total=overall.get("bytes_total"),
                stage=str(db.get("stage") or ""),
                ui_stage=ui_stage,
            )
        )
    else:
        overall_line = f"{float(percent):.1f}%"
    db_done = db.get("bytes_produced")
    db_total = db.get("bytes_estimated")
    if str(db.get("stage") or "") == STAGE_TRANSFERRING:
        db_done = db.get("bytes_transferred")
        db_total = db.get("bytes_total")
    db_progress = db.get("progress_label") or progress_label(
        done=db_done,
        total=db_total,
        stage=str(db.get("stage") or ""),
        ui_stage=ui_stage,
    )
    files_done = overall.get("files_done")
    files_total = overall.get("files_total")
    objects_done = overall.get("objects_done")
    objects_total = overall.get("objects_total")
    speed = overall.get("speed_bps") or db.get("speed_bps")
    eta = overall.get("eta_seconds")
    if eta is None:
        eta = eta_seconds(done=overall.get("bytes_done"), total=overall.get("bytes_total"), speed_bps=speed)
    status = str(data.get("status") or db.get("status") or "—")
    stage_line = friendly_stage(ui_stage, data)
    if ui_stage == UI_DATABASE or stage_line == UI_DATABASE:
        if db.get("stage"):
            stage_line = f"{UI_DATABASE} / {db.get('stage')}"
    files_discovered = files_total if files_total is not None else overall.get("files_discovered")
    ssh_action = str(data.get("ssh_action") or "")
    transferred_line = progress_label(
        done=overall.get("bytes_done"),
        total=overall.get("bytes_total"),
        stage=str(db.get("stage") or ""),
        ui_stage=ui_stage,
    )
    head_state = data.get("head_state") or master.get("head_state") or "UNCHANGED"
    committed = master.get("committed_bytes")
    staged = master.get("staged_bytes")
    written = master.get("write_bytes")
    write_objects = master.get("write_objects")
    staging_objects = master.get("staging_objects")
    staging_bytes = master.get("staging_bytes")
    master_size = master.get("current_size")
    if master_size is None:
        master_size = written if written is not None else 0
    lines = [
        str(operation),
        "",
        f"Overall: {overall_line}",
        f"Stage: {stage_line}",
        f"Status: {status}",
        *([f"SSH action: {ssh_action}"] if ssh_action else []),
        "",
        "Transfer:",
        f"Transferred: {transferred_line}",
        f"Speed: {speed_label(speed)}",
        f"Elapsed: {format_hms(elapsed)}",
        f"ETA: {format_hms(eta)}",
        "",
        "Files:",
        f"Files discovered: {files_discovered if files_discovered is not None else '—'}",
        f"Files processed: {files_done if files_done is not None else '—'} / {files_total if files_total is not None else '—'}",
        "",
        "Objects:",
        f"Objects processed: {objects_done if objects_done is not None else '—'} / {objects_total if objects_total is not None else '—'}",
        "",
        "Current:",
        f"Application: {data.get('application') or '—'}",
        f"Source: {data.get('current_source') or overall.get('current_source') or '—'}",
        f"Current file/object: {data.get('current_object') or overall.get('current_object') or '—'}",
        "",
        "Database:",
        f"Database: {db.get('name') or '—'}",
        f"Database type: {db.get('type') or '—'}",
        f"Stage: {db.get('stage') or '—'}",
        f"Bytes produced: {progress_label(done=db.get('bytes_produced'), total=db.get('bytes_estimated'), stage=str(db.get('stage') or ''), ui_stage=ui_stage)}",
        f"Bytes transferred: {progress_label(done=db.get('bytes_transferred'), total=db.get('bytes_total'), stage=str(db.get('stage') or STAGE_TRANSFERRING), ui_stage=ui_stage)}",
        f"Speed: {speed_label(db.get('speed_bps'))}",
        f"Progress: {db_progress}",
        "",
        "MASTER:",
        f"Current size: {format_bytes(master_size or 0)}",
        f"Transferred bytes: {format_bytes(int(overall.get('bytes_done') or 0))}",
        f"Staged bytes: {format_bytes(int(staged or 0))}",
        f"Committed master bytes: {format_bytes(int(committed or 0))}",
        f"MASTER WRITES: {write_objects if write_objects is not None else 0} objects / {format_bytes(int(written or 0))}",
        f"STAGING: {staging_objects if staging_objects is not None else 0} objects / {format_bytes(int(staging_bytes or 0))}",
        f"HEAD: {head_state}",
        f"Staging: {data.get('staging_state') or '—'}",
    ]
    if str(data.get("status") or "").lower() in {"failed", "cancelled"}:
        lines.extend(
            [
                "",
                "BACKUP FAILED" if str(data.get("status") or "").lower() == "failed" else "BACKUP CANCELLED",
                f"Error: {data.get('error') or data.get('message') or '—'}",
                f"Operation ID: {data.get('backup_id') or '—'}",
                f"HEAD: {head_state}",
                f"Staging: {data.get('staging_state') or 'CLEANED'}",
            ]
        )
    return "\n".join(lines)


def format_live_backup_rows(progress: Mapping[str, Any] | None, *, now: float | None = None) -> list[tuple[str, str]]:
    """Dashboard rows for the LIVE BACKUP card. Same rules as the text panel."""
    panel = format_live_backup_panel(progress, now=now)
    rows: list[tuple[str, str]] = []
    for line in panel.splitlines():
        if not line.strip():
            continue
        if ":" in line and not line.startswith("BACKUP"):
            key, value = line.split(":", 1)
            rows.append((f"{key.strip()}:", value.strip()))
        elif not rows:
            rows.append(("Operation:", line.strip()))
    return rows


class BackupLiveSession:
    """Writes real pipeline events to progress.json. Never fakes a percentage."""

    def __init__(self, reporter, *, operation: str, backup_id: str = "", applications: list[dict[str, Any]] | None = None) -> None:
        self.reporter = reporter
        self.operation = operation
        self.backup_id = backup_id
        self.applications = list(applications or [])
        existing = {}
        try:
            existing = dict(reporter.read() or {})
        except Exception:
            existing = {}
        try:
            self.started_at = float(existing.get("started_at") or time.time())
        except (TypeError, ValueError):
            self.started_at = time.time()
        self._last_bytes = 0
        self._last_t = self.started_at
        self._last_publish = 0.0
        self.overall: dict[str, Any] = {
            "label": "Preparing...",
            "percent": None,
            "bytes_done": 0,
            "bytes_total": 0,
            "files_done": 0,
            "files_total": None,
            "objects_done": 0,
            "objects_total": None,
            "speed_bps": 0,
            "eta_seconds": None,
            "file_bytes_complete": 0,
            "dump_bytes_complete": 0,
            "dump_bytes_total": 0,
        }
        self.database: dict[str, Any] = {}
        self.application = ""
        self.phase = "master"
        self.ui_stage = UI_PREPARING
        self.ssh_action = ""
        self.last_stage = UI_PREPARING
        self.message = operation
        self.current_source = ""
        self.current_object = ""
        self.head_state = "UNCHANGED"
        self.staging_state = "—"
        self.master = {
            "current_size": 0,
            "write_bytes": 0,
            "write_objects": 0,
            "staged_bytes": 0,
            "staging_bytes": 0,
            "staging_objects": 0,
            "committed_bytes": 0,
            "head_state": "UNCHANGED",
        }

    def _speed(self, bytes_now: int) -> float:
        now = time.time()
        dt = now - self._last_t
        delta = int(bytes_now) - int(self._last_bytes)
        self._last_bytes = int(bytes_now)
        self._last_t = now
        if dt <= 0 or delta < 0:
            return float(self.overall.get("speed_bps") or 0)
        return delta / dt

    def publish(self, *, phase: str | None = None, message: str | None = None) -> None:
        if phase:
            self.phase = phase
        if message:
            self.message = message
        elapsed = max(0, int(time.time() - self.started_at))
        percent = measurable_percent(
            self.overall.get("bytes_done"),
            self.overall.get("bytes_total"),
            stage=str(self.database.get("stage") or self.phase or ""),
        )
        self.overall["percent"] = percent
        if percent is None:
            self.overall["label"] = progress_label(
                done=self.overall.get("bytes_done"),
                total=self.overall.get("bytes_total"),
                stage=str(self.database.get("stage") or ""),
                ui_stage=self.ui_stage,
            )
        else:
            self.overall["label"] = f"{float(percent):.1f}%"
        self.overall["eta_seconds"] = eta_seconds(
            done=self.overall.get("bytes_done"),
            total=self.overall.get("bytes_total"),
            speed_bps=self.overall.get("speed_bps"),
        )
        self.master["head_state"] = self.head_state
        self.master["current_size"] = int(self.master.get("write_bytes") or 0) + int(self.master.get("committed_bytes") or 0)
        self.reporter.write(
            status="running",
            phase=self.phase,
            ui_stage=self.ui_stage,
            last_stage=self.last_stage,
            ssh_action=self.ssh_action or None,
            message=self.message,
            backup_id=self.backup_id,
            started_at=self.started_at,
            elapsed_seconds=elapsed,
            operation=self.operation,
            application=self.application or None,
            current_source=self.current_source or None,
            current_object=self.current_object or None,
            database=dict(self.database),
            overall=dict(self.overall),
            master=dict(self.master),
            head_state=self.head_state,
            staging_state=self.staging_state,
            bytes_done=int(self.overall.get("bytes_done") or 0),
            bytes_total=int(self.overall.get("bytes_total") or 0),
            speed_bps=int(self.overall.get("speed_bps") or 0),
            eta_seconds=self.overall.get("eta_seconds"),
        )

    def set_file_totals(self, *, files_total: int, bytes_total: int) -> None:
        self.overall["files_total"] = files_total
        self.overall["objects_total"] = files_total
        self.overall["bytes_total"] = bytes_total if bytes_total > 0 else 0
        self.ui_stage = UI_TRANSFERRING
        self.last_stage = UI_TRANSFERRING
        self.publish(phase="transferring", message="Transferring changed objects…")

    def set_ui_stage(self, ui_stage: str, message: str | None = None, *, phase: str | None = None) -> None:
        self.ui_stage = ui_stage
        if ui_stage not in {UI_FAILED, UI_CANCELLED, UI_SUCCESS}:
            self.last_stage = ui_stage
        if phase:
            self.phase = phase
        self.publish(phase=self.phase, message=message)

    def note_master_write(self, size: int) -> None:
        self.master["write_objects"] = int(self.master.get("write_objects") or 0) + 1
        self.master["write_bytes"] = int(self.master.get("write_bytes") or 0) + max(0, int(size))
        self.master["staged_bytes"] = int(self.master.get("write_bytes") or 0)
        self.master["current_size"] = int(self.master.get("write_bytes") or 0)

    def set_committed(self, bytes_count: int, *, generation: int | None = None) -> None:
        self.master["committed_bytes"] = int(bytes_count)
        if generation is not None:
            self.head_state = str(generation)
            self.master["head_state"] = str(generation)

    def finish(self, status: str, ui_stage: str, message: str, *, error: str = "", staging_state: str = "CLEANED") -> None:
        if self.ui_stage not in {UI_FAILED, UI_CANCELLED, UI_SUCCESS}:
            self.last_stage = self.ui_stage
        self.ui_stage = ui_stage
        self.staging_state = staging_state
        elapsed = max(0, int(time.time() - self.started_at))
        percent = measurable_percent(
            self.overall.get("bytes_done"),
            self.overall.get("bytes_total"),
            stage=str(self.database.get("stage") or self.phase or ""),
        )
        if percent is not None:
            self.overall["percent"] = percent
            self.overall["label"] = f"{float(percent):.1f}%"
        self.reporter.write(
            status=status,
            phase=self.phase,
            ui_stage=ui_stage,
            last_stage=self.last_stage,
            ssh_action=self.ssh_action or None,
            message=message,
            error=error or None,
            backup_id=self.backup_id,
            started_at=self.started_at,
            elapsed_seconds=elapsed,
            operation=self.operation,
            application=self.application or None,
            current_source=self.current_source or None,
            current_object=self.current_object or None,
            database=dict(self.database),
            overall=dict(self.overall),
            master=dict(self.master),
            head_state=self.head_state,
            staging_state=staging_state,
            bytes_done=int(self.overall.get("bytes_done") or 0),
            bytes_total=int(self.overall.get("bytes_total") or 0),
            speed_bps=int(self.overall.get("speed_bps") or 0),
            eta_seconds=self.overall.get("eta_seconds"),
        )

    def apply_dump_estimates(self, estimates: dict[str, int]) -> None:
        total = sum(int(value or 0) for value in estimates.values())
        self.overall["dump_estimates"] = {str(key): int(value or 0) for key, value in estimates.items()}
        self.overall["dump_bytes_total"] = total if total > 0 else 0
        base = int(self.overall.get("file_bytes_complete") or 0)
        if total > 0:
            self.overall["bytes_total"] = base + total
            self.overall["bytes_done"] = base + int(self.overall.get("dump_bytes_complete") or 0)
        self.publish(phase="database", message="Measuring database sizes…")

    def file_progress(
        self,
        *,
        files_done: int,
        objects_done: int,
        bytes_done: int,
        source_root: str = "",
        current_object: str = "",
    ) -> None:
        previous_done = int(self.overall.get("bytes_done") or 0)
        self.overall["files_done"] = files_done
        self.overall["objects_done"] = objects_done
        self.overall["bytes_done"] = bytes_done
        self.overall["speed_bps"] = self._speed(bytes_done)
        self.master["staged_bytes"] = bytes_done
        if source_root:
            self.application = application_for_root(self.applications, source_root)
            self.current_source = source_root
        if current_object:
            self.current_object = current_object
            self.overall["current_object"] = current_object
            self.overall["current_source"] = self.current_source
        now = time.time()
        force = False
        totals = self.overall.get("files_total")
        if totals and files_done >= int(totals):
            force = True
        if force or now - self._last_publish >= 0.25 or bytes_done != previous_done:
            self._last_publish = now
            self.publish(phase="transferring", message="Transferring changed objects…")

    def database_event(
        self,
        *,
        name: str,
        stage: str,
        status: str = "running",
        db_type: str = "MariaDB",
        bytes_produced: int | None = None,
        bytes_transferred: int | None = None,
        bytes_estimated: int | None = None,
        bytes_total: int | None = None,
        elapsed_seconds: int | None = None,
        error: str = "",
    ) -> None:
        self.application = application_for_database(self.applications, name) or self.application
        self.ui_stage = UI_DATABASE
        self.last_stage = UI_DATABASE
        produced = bytes_produced if bytes_produced is not None else self.database.get("bytes_produced")
        transferred = bytes_transferred if bytes_transferred is not None else self.database.get("bytes_transferred")
        estimated = bytes_estimated if bytes_estimated is not None else self.database.get("bytes_estimated")
        total = bytes_total if bytes_total is not None else self.database.get("bytes_total")
        current_bytes = transferred if stage == STAGE_TRANSFERRING else produced
        if str(self.database.get("stage") or "") != stage:
            self._last_bytes = int(current_bytes or 0)
            self._last_t = time.time()
            speed = float(self.overall.get("speed_bps") or 0)
        else:
            speed = self._speed(int(current_bytes or 0)) if current_bytes is not None else 0
        compare_done = transferred if stage == STAGE_TRANSFERRING else produced
        compare_total = total if stage == STAGE_TRANSFERRING else estimated
        self.database = {
            "name": name,
            "type": db_type,
            "stage": stage,
            "status": status,
            "elapsed_seconds": elapsed_seconds if elapsed_seconds is not None else max(0, int(time.time() - self.started_at)),
            "bytes_produced": produced,
            "bytes_transferred": transferred,
            "bytes_estimated": estimated,
            "bytes_total": total,
            "speed_bps": speed,
            "eta_seconds": eta_seconds(done=compare_done, total=compare_total, speed_bps=speed),
            "progress_label": progress_label(done=compare_done, total=compare_total, stage=stage),
            "error": error or None,
        }
        if stage == STAGE_DUMPING and produced is not None:
            base = int(self.overall.get("file_bytes_complete") or 0)
            completed = int(self.overall.get("dump_bytes_complete") or 0)
            self.overall["bytes_done"] = base + completed + int(produced)
            dump_total = int(self.overall.get("dump_bytes_total") or 0)
            current_est = int(estimated or 0)
            extra = max(0, int(produced) - current_est) if current_est else 0
            if dump_total > 0:
                self.overall["bytes_total"] = base + dump_total + extra
            elif current_est > 0:
                self.overall["bytes_total"] = base + max(current_est, int(produced))
            self.overall["speed_bps"] = speed
        if stage == STAGE_TRANSFERRING and transferred is not None:
            base = int(self.overall.get("file_bytes_complete") or 0)
            completed = int(self.overall.get("dump_bytes_complete") or 0)
            self.overall["bytes_done"] = base + completed + int(transferred)
            dump_total = int(self.overall.get("dump_bytes_total") or 0)
            if total:
                remaining = max(0, dump_total - int(self.database.get("bytes_total") or total or 0))
                self.overall["bytes_total"] = base + completed + int(total) + remaining
            self.overall["speed_bps"] = speed
        if stage == STAGE_COMPLETE:
            added = int(transferred or total or produced or 0)
            self.overall["dump_bytes_complete"] = int(self.overall.get("dump_bytes_complete") or 0) + added
            self.overall["objects_done"] = int(self.overall.get("objects_done") or 0) + 1
        self.publish(phase="database", message=f"{stage}: {name}")

