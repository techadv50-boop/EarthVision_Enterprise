#!/usr/bin/env python3
"""Restricted plugin worker HTTP server (P2A) — stdlib only.

Isolation fail-closed:
  - Refuses to start if Host Shell secrets / DB URL / Docker socket env present
  - Binds to 0.0.0.0 inside the container network only (compose attaches internal net)
  - No Host Shell ``app`` package on sys.path
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# Ensure local imports work when executed as a script
sys.path.insert(0, str(Path(__file__).resolve().parent))

from contract import (  # noqa: E402
    ContractError,
    make_error,
    make_response,
    validate_request,
)
from executor import ExecError, execute  # noqa: E402

FORBIDDEN_ENV = (
    "DATABASE_URL",
    "SECRET_KEY",
    "MASTER_PASSWORD",
    "ADMIN_PASSWORD",
    "DOCKER_HOST",
    "DOCKER_SOCK",
    "AWS_SECRET_ACCESS_KEY",
    "OPENAI_API_KEY",
)


def assert_isolation_or_die() -> dict[str, Any]:
    """Fail closed if worker isolation cannot be established."""
    problems: list[str] = []
    for key in FORBIDDEN_ENV:
        if os.environ.get(key):
            problems.append(f"forbidden env present: {key}")
    if os.path.exists("/var/run/docker.sock"):
        problems.append("docker.sock is mounted")
    if os.geteuid() == 0 and os.environ.get("EV_PLUGIN_WORKER_ALLOW_ROOT") != "1":
        problems.append("running as root")
    arts = os.environ.get("EV_ARTIFACTS_ROOT")
    if not arts:
        problems.append("EV_ARTIFACTS_ROOT missing")
    elif not Path(arts).is_dir():
        problems.append("EV_ARTIFACTS_ROOT is not a directory")
    # Refuse Host Shell import path
    for p in sys.path:
        if p.endswith("/backend") or p.endswith("/app") or "/backend/app" in p.replace("\\", "/"):
            # Allow empty/std; reject explicit backend tree if added
            if Path(p).name in {"backend", "app"} and (Path(p) / "app").exists():
                problems.append(f"Host Shell path on sys.path: {p}")
    report = {
        "isolated": not problems,
        "problems": problems,
        "uid": os.geteuid(),
        "artifacts_root": arts,
        "readonly_hint": os.environ.get("EV_PLUGIN_WORKER_READONLY", "unknown"),
    }
    if problems:
        print("PLUGIN WORKER ISOLATION FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        raise SystemExit(2)
    return report


ISOLATION_REPORT = assert_isolation_or_die()
TIMEOUT_SEC = float(os.environ.get("EV_PLUGIN_WORKER_TIMEOUT_SEC", "5"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        sys.stderr.write("worker: " + (fmt % args) + "\n")

    def _send(self, code: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/health", "/isolation"}:
            self._send(
                200,
                {
                    "ok": True,
                    "service": "sateye-plugin-worker",
                    "isolation": ISOLATION_REPORT,
                },
            )
            return
        self._send(404, make_error(request_id=None, error="not found", code="not_found"))

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/execute":
            self._send(404, make_error(request_id=None, error="not found", code="not_found"))
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 1_000_000:
            self._send(
                400,
                make_error(request_id=None, error="invalid content length", code="bad_request"),
            )
            return
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            req = validate_request(data)
            result = execute(
                plugin_id=req["plugin_id"],
                version=req["version"],
                digest=req["digest"],
                operation=req["operation"],
                payload=req["payload"],
                timeout_sec=TIMEOUT_SEC,
            )
            self._send(
                200,
                make_response(
                    request_id=req["request_id"],
                    plugin_id=req["plugin_id"],
                    version=req["version"],
                    digest=req["digest"],
                    result=result,
                ),
            )
        except (ContractError, ExecError, json.JSONDecodeError) as exc:
            rid = None
            try:
                rid = data.get("request_id") if isinstance(data, dict) else None
            except Exception:  # noqa: BLE001
                rid = None
            self._send(
                400,
                make_error(request_id=rid, error=str(exc), code="exec_rejected"),
            )


def main() -> int:
    host = os.environ.get("EV_PLUGIN_WORKER_HOST", "0.0.0.0")
    port = int(os.environ.get("EV_PLUGIN_WORKER_PORT", "8091"))
    print(
        json.dumps(
            {
                "service": "sateye-plugin-worker",
                "host": host,
                "port": port,
                "isolation": ISOLATION_REPORT,
            }
        ),
        flush=True,
    )
    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
