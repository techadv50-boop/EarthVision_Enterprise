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


def measurable_percent(
    done: int | float | None,
    total: int | float | None,
    *,
    stage: str = "",
) -> int | None:
    """Return 0-100 only when both values are real and total > 0. Never invent a percent."""
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
        # Schema-size estimates can undershoot mysqldump output. Do not claim 100%.
        if stage == STAGE_DUMPING:
            return 99
        return None
    percent = int(done_n * 100 / total_n)
    if percent >= 100 and stage == STAGE_DUMPING:
        return 99
    return min(100, percent)


def progress_label(*, done: int | None, total: int | None, stage: str = "") -> str:
    if stage in PREPARING_STAGES or (not done and stage == STAGE_DUMPING and not total):
        if stage == STAGE_DUMPING:
            return "Calculating..."
        return "Preparing..."
    if done is None or done < 0:
        if stage in MEASURING_STAGES:
            return "Calculating..."
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
    overall_line = f"{percent}%" if percent is not None else str(
        overall.get("label") or progress_label(
            done=overall.get("bytes_done"),
            total=overall.get("bytes_total"),
            stage=str(db.get("stage") or data.get("phase") or ""),
        )
    )
    db_done = db.get("bytes_transferred") if str(db.get("stage") or "") == STAGE_TRANSFERRING else db.get("bytes_produced")
    db_total = db.get("bytes_estimated") if str(db.get("stage") or "") != STAGE_TRANSFERRING else db.get("bytes_total")
    if str(db.get("stage") or "") == STAGE_TRANSFERRING:
        db_done = db.get("bytes_transferred")
        db_total = db.get("bytes_total")
    db_progress = db.get("progress_label") or progress_label(
        done=db_done,
        total=db_total,
        stage=str(db.get("stage") or ""),
    )
    files_done = overall.get("files_done")
    files_total = overall.get("files_total")
    objects_done = overall.get("objects_done")
    objects_total = overall.get("objects_total")
    speed = overall.get("speed_bps") or db.get("speed_bps")
    eta = overall.get("eta_seconds")
    if eta is None:
        eta = eta_seconds(done=overall.get("bytes_done"), total=overall.get("bytes_total"), speed_bps=speed)
    lines = [
        str(operation),
        "",
        f"Overall: {overall_line}",
        f"Application: {data.get('application') or '—'}",
        f"Database: {db.get('name') or '—'}",
        f"Database type: {db.get('type') or '—'}",
        f"Stage: {db.get('stage') or data.get('phase') or '—'}",
        f"Status: {db.get('status') or data.get('status') or '—'}",
        f"Database: {db_progress}",
        f"Speed: {speed_label(speed)}",
        f"Elapsed: {format_hms(elapsed)}",
        f"ETA: {format_hms(eta)}",
        f"Files: {files_done if files_done is not None else '—'} / {files_total if files_total is not None else '—'}",
        f"Objects: {objects_done if objects_done is not None else '—'} / {objects_total if objects_total is not None else '—'}",
        f"Bytes transferred: {progress_label(done=overall.get('bytes_done'), total=overall.get('bytes_total'))}",
    ]
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
        self.message = operation

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
            stage = str(self.database.get("stage") or "")
            self.overall["label"] = progress_label(
                done=self.overall.get("bytes_done"),
                total=self.overall.get("bytes_total"),
                stage=stage,
            )
        else:
            self.overall["label"] = f"{percent}%"
        self.overall["eta_seconds"] = eta_seconds(
            done=self.overall.get("bytes_done"),
            total=self.overall.get("bytes_total"),
            speed_bps=self.overall.get("speed_bps"),
        )
        self.reporter.write(
            status="running",
            phase=self.phase,
            message=self.message,
            backup_id=self.backup_id,
            started_at=self.started_at,
            elapsed_seconds=elapsed,
            operation=self.operation,
            application=self.application or None,
            database=dict(self.database),
            overall=dict(self.overall),
            bytes_done=int(self.overall.get("bytes_done") or 0),
            bytes_total=int(self.overall.get("bytes_total") or 0),
            speed_bps=int(self.overall.get("speed_bps") or 0),
            eta_seconds=self.overall.get("eta_seconds"),
        )

    def set_file_totals(self, *, files_total: int, bytes_total: int) -> None:
        self.overall["files_total"] = files_total
        self.overall["objects_total"] = files_total
        self.overall["bytes_total"] = bytes_total if bytes_total > 0 else 0
        self.publish(phase="transferring", message="Transferring changed objects…")

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
    ) -> None:
        self.overall["files_done"] = files_done
        self.overall["objects_done"] = objects_done
        self.overall["bytes_done"] = bytes_done
        self.overall["speed_bps"] = self._speed(bytes_done)
        if source_root:
            self.application = application_for_root(self.applications, source_root)
        now = time.time()
        force = False
        totals = self.overall.get("files_total")
        if totals and files_done >= int(totals):
            force = True
        if force or now - self._last_publish >= 0.25:
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

