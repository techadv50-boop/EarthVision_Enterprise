from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from app.constants import APP_ID, MUTEX_NAME


@dataclass(frozen=True)
class AgentPaths:
    root: Path
    config_file: Path
    state_file: Path
    status_file: Path
    audit_db: Path
    log_file: Path
    lock_file: Path
    mutex_name: str = MUTEX_NAME

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(parents=True, exist_ok=True)


def resolve_paths(root: Path | None = None) -> AgentPaths:
    if root is None:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_STATE_HOME")
        if base:
            root = Path(base) / APP_ID
        else:
            root = Path.home() / ".local" / "share" / APP_ID
    root = Path(root)
    logs = root / "logs"
    return AgentPaths(
        root=root,
        config_file=root / "config.json",
        state_file=root / "state.json",
        status_file=root / "agent.status.json",
        audit_db=root / "audit.sqlite",
        log_file=logs / "agent.log",
        lock_file=root / "agent.lock",
    )


def launch_command(*, background: bool = True) -> str:
    """Command written to the Windows Run key for automatic start."""
    flag = " --background" if background else ""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"{flag}'
    main = Path(__file__).resolve().parents[1] / "main.py"
    return f'"{sys.executable}" "{main}"{flag}'
