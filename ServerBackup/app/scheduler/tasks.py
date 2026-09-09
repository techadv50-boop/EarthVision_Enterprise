"""Windows Task Scheduler integration. Default is OFF. Same engine as BACKUP NOW."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.config.schema import AppConfig
from app.config.store import default_config_path

TASK_NAME = "ServerBackup-Ubuntu"


def _executable() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--backup", "--mode", "scheduled"]
    return [sys.executable, "-m", "app.main", "--backup", "--mode", "scheduled"]


def _quoted(args: list[str]) -> str:
    return " ".join(f'"{part}"' for part in args)


def enable_schedule(config: AppConfig) -> str:
    if os.name != "nt":
        raise RuntimeError("Windows Task Scheduler is only available on Windows.")
    schtasks = shutil.which("schtasks")
    if not schtasks:
        raise RuntimeError("schtasks.exe was not found.")
    command = _quoted(_executable() + ["--config", str(default_config_path())])
    # schtasks /Create arguments are constructed as an argv list (no shell).
    args = [
        schtasks,
        "/Create",
        "/F",
        "/TN",
        TASK_NAME,
        "/TR",
        command,
        "/SC",
        _sc(config.schedule_type),
        "/ST",
        config.schedule_time,
        "/RL",
        "LIMITED",
    ]
    if config.schedule_type.lower() == "weekly":
        args.extend(["/D", config.schedule_weekday.upper()[:3]])
    completed = subprocess.run(args, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Failed to create scheduled task.")
    return completed.stdout.strip() or "Scheduled task created."


def disable_schedule() -> str:
    if os.name != "nt":
        return "Scheduling is only applied on Windows."
    schtasks = shutil.which("schtasks")
    if not schtasks:
        raise RuntimeError("schtasks.exe was not found.")
    args = [schtasks, "/Delete", "/F", "/TN", TASK_NAME]
    completed = subprocess.run(args, capture_output=True, text=True, check=False)
    if completed.returncode != 0 and "cannot find" not in (completed.stderr + completed.stdout).lower():
        raise RuntimeError(completed.stderr.strip() or "Failed to remove scheduled task.")
    return "Automatic backup is OFF."


def schedule_status() -> dict[str, str]:
    if os.name != "nt":
        return {"enabled": "no", "detail": "Task Scheduler is Windows-only."}
    schtasks = shutil.which("schtasks")
    if not schtasks:
        return {"enabled": "unknown", "detail": "schtasks.exe was not found."}
    completed = subprocess.run(
        [schtasks, "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {"enabled": "no", "detail": "No scheduled task."}
    return {"enabled": "yes", "detail": completed.stdout.strip()}


def _sc(schedule_type: str) -> str:
    mapping = {"daily": "DAILY", "weekly": "WEEKLY", "custom": "DAILY"}
    return mapping.get(schedule_type.lower(), "DAILY")


def engine_command_for_scripts() -> str:
    """Used by PowerShell helper scripts."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        return f'"{exe}" --backup --mode scheduled --config "{default_config_path()}"'
    python = Path(sys.executable)
    return f'"{python}" -m app.main --backup --mode scheduled --config "{default_config_path()}"'
