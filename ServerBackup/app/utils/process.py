"""Launch the same backup engine as a detached process so the GUI can close."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def engine_argv(cli_args: list[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *cli_args]
    module = ["-m", "app.main", *cli_args]
    return [sys.executable, *module]


def spawn_detached(cli_args: list[str], *, cwd: Path | None = None) -> subprocess.Popen:
    args = engine_argv(cli_args)
    env = os.environ.copy()
    if cwd and not getattr(sys, "frozen", False):
        env["PYTHONPATH"] = str(cwd) + os.pathsep + env.get("PYTHONPATH", "")
    kwargs: dict = {
        "cwd": str(cwd) if cwd and not getattr(sys, "frozen", False) else None,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "env": env,
    }
    if os.name == "nt":
        flags = 0
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        kwargs["creationflags"] = flags
        kwargs["start_new_session"] = True
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(args, **{k: v for k, v in kwargs.items() if v is not None or k in {"stdin", "stdout", "stderr"}})
