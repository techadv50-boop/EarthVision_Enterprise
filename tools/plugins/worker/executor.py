"""Parent-side execution: spawn an isolated child process per request.

On timeout the child is SIGKILL'd and reaped. Thread-based execution is gone.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from executor_core import ExecError  # noqa: F401 — re-export
from executor_core import verify_artifact
from signatures import verify_pack_signature


def _child_script() -> Path:
    return Path(__file__).resolve().parent / "child_runner.py"


def execute(
    *,
    plugin_id: str,
    version: str,
    digest: str,
    operation: str,
    payload: dict[str, Any],
    timeout_sec: float = 5.0,
) -> dict[str, Any]:
    """Verify then run plugin in a dedicated child process."""
    # Parent pre-check (also done again in child) — fail fast before spawn
    root = verify_artifact(plugin_id, version, digest)
    verify_pack_signature(root, digest)

    if operation == "ping":
        # Still go through child for consistent isolation surface
        pass

    req = {
        "plugin_id": plugin_id,
        "version": version,
        "digest": digest,
        "operation": operation,
        "payload": payload,
    }
    env = os.environ.copy()
    # Never pass Host Shell secrets into the child even if parent somehow has them
    for k in (
        "DATABASE_URL",
        "SECRET_KEY",
        "MASTER_PASSWORD",
        "ADMIN_PASSWORD",
        "DOCKER_HOST",
        "AWS_SECRET_ACCESS_KEY",
    ):
        env.pop(k, None)

    proc = subprocess.Popen(
        [sys.executable, str(_child_script())],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(_child_script().parent),
        start_new_session=True,  # own process group for killpg
    )
    try:
        assert proc.stdin is not None and proc.stdout is not None
        out_b, err_b = proc.communicate(
            input=json.dumps(req).encode("utf-8"),
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        _kill_and_reap(proc)
        raise ExecError(
            f"plugin execution timed out after {timeout_sec}s (child terminated)"
        ) from exc

    if proc.returncode != 0 and not out_b:
        raise ExecError(
            f"plugin child failed rc={proc.returncode}: {(err_b or b'').decode('utf-8', 'replace')[:400]}"
        )
    try:
        data = json.loads(out_b.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ExecError(
            f"plugin child returned invalid JSON (rc={proc.returncode}): "
            f"{(out_b or b'')[:200]!r}"
        ) from exc
    if not data.get("ok"):
        raise ExecError(str(data.get("error") or "plugin child rejected execution"))
    result = data.get("result")
    if not isinstance(result, dict):
        raise ExecError("plugin child returned invalid result")
    return result


def _kill_and_reap(proc: subprocess.Popen[bytes]) -> None:
    """SIGKILL the process group and reap to avoid zombies."""
    try:
        if proc.pid:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
    finally:
        try:
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
                proc.wait(timeout=1)
            except Exception:  # noqa: BLE001
                pass
        # Drain pipes if still open
        try:
            if proc.stdout:
                proc.stdout.read()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.01)
