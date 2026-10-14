#!/usr/bin/env python3
"""Per-request child process: verify + execute plugin under resource/network limits.

Invoked by the worker parent via subprocess. Communicates via JSON on stdin/stdout.
"""

from __future__ import annotations

import json
import os
import resource
import socket
import sys
import traceback
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from executor_core import (  # noqa: E402
    ExecError,
    load_and_render,
    verify_artifact,
)
from signatures import SignatureError, verify_pack_signature  # noqa: E402


def _deny_network() -> None:
    """Fail closed: plugin code must not open sockets."""

    def _blocked(*_a: Any, **_k: Any) -> Any:
        raise OSError("network disabled in plugin worker child process")

    socket.socket = _blocked  # type: ignore[misc, assignment]
    socket.create_connection = _blocked  # type: ignore[assignment]
    socket.create_server = _blocked  # type: ignore[attr-defined, assignment]
    if hasattr(socket, "socketpair"):
        socket.socketpair = _blocked  # type: ignore[assignment]


def _apply_resource_limits() -> None:
    # Address space (virtual memory) — soft fail on exhaustion
    as_bytes = int(os.environ.get("EV_PLUGIN_CHILD_AS_BYTES", str(256 * 1024 * 1024)))
    cpu_sec = int(os.environ.get("EV_PLUGIN_CHILD_CPU_SEC", "5"))
    nproc = int(os.environ.get("EV_PLUGIN_CHILD_NPROC", "32"))
    nofile = int(os.environ.get("EV_PLUGIN_CHILD_NOFILE", "64"))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (as_bytes, as_bytes))
    except (ValueError, OSError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_sec, cpu_sec))
    except (ValueError, OSError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (nproc, nproc))
    except (ValueError, OSError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
    except (ValueError, OSError):
        pass
    # Core dumps off
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, OSError):
        pass


def main() -> int:
    try:
        raw = sys.stdin.read()
        req = json.loads(raw)
        _apply_resource_limits()
        _deny_network()
        plugin_id = str(req["plugin_id"])
        version = str(req["version"])
        digest = str(req["digest"])
        operation = str(req.get("operation") or "render")
        payload = req.get("payload") or {}
        root = verify_artifact(plugin_id, version, digest)
        verify_pack_signature(root, digest)
        if operation == "ping":
            out = {"pong": True, "plugin_id": plugin_id, "version": version}
        else:
            out = load_and_render(plugin_id, version, root, payload)
        sys.stdout.write(json.dumps({"ok": True, "result": out}))
        return 0
    except (ExecError, SignatureError, KeyError, TypeError, ValueError, OSError, MemoryError) as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    except BaseException as exc:  # noqa: BLE001
        sys.stdout.write(
            json.dumps({"ok": False, "error": f"child crash: {exc}", "trace": traceback.format_exc()[-500:]})
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
