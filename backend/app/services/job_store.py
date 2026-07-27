"""In-memory async job store for long analytics renders (Serveo ~5s proxy limit)."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_TTL_SEC = 30 * 60


def create_job(kind: str) -> str:
    job_id = f"{kind}_{uuid.uuid4().hex[:16]}"
    with _LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "kind": kind,
            "status": "pending",
            "result": None,
            "error": None,
            "created_at": time.time(),
        }
    return job_id


def set_job_done(job_id: str, result: dict[str, Any]) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["status"] = "done"
        job["result"] = result
        job["error"] = None


def set_job_error(job_id: str, message: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["status"] = "error"
        job["error"] = message


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        # Expire old jobs
        if time.time() - float(job.get("created_at") or 0) > _TTL_SEC:
            _JOBS.pop(job_id, None)
            return None
        return dict(job)
