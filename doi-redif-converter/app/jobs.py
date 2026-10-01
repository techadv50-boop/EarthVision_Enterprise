"""In-memory conversion jobs with live progress tracking."""

from __future__ import annotations

import asyncio
import io
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from typing import Any, Callable

from .extractor import extract_many
from .models import ArticleMeta
from .redif import build_filename, to_redif
from .report import build_summary, failed_entries, format_failed_csv, format_report_text


@dataclass
class JobState:
    id: str
    status: str = "queued"  # queued | running | completed | failed
    total: int = 0
    done: int = 0
    succeeded: int = 0
    failed: int = 0
    current_doi: str = ""
    recent: list[dict[str, Any]] = field(default_factory=list)
    results: list[Any] = field(default_factory=list)
    metas: list[ArticleMeta] = field(default_factory=list)
    handle_prefix: str = ""
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def left(self) -> int:
        return max(0, self.total - self.done)

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 0.0
        return round(100.0 * self.done / self.total, 1)

    def snapshot(self, include_results: bool = False) -> dict[str, Any]:
        with self._lock:
            elapsed = None
            if self.started_at:
                end = self.finished_at or time.time()
                elapsed = round(end - self.started_at, 1)
            eta = None
            if self.done > 0 and self.left > 0 and self.started_at:
                rate = self.done / max(0.001, (time.time() - self.started_at))
                eta = round(self.left / rate, 1) if rate > 0 else None
            if self.metas:
                failed_dois = failed_entries(self.metas)
            else:
                failed_dois = [
                    {
                        "doi": r.get("doi", ""),
                        "error": r.get("error") or "Unknown error",
                    }
                    for r in self.recent
                    if not r.get("ok")
                ]
            summary = build_summary(
                total=self.total,
                succeeded=self.succeeded,
                failed=self.failed,
                failed_dois=failed_dois,
                elapsed_sec=elapsed,
            )
            data = {
                "job_id": self.id,
                "status": self.status,
                "total": self.total,
                "done": self.done,
                "left": self.left,
                "succeeded": self.succeeded,
                "failed": self.failed,
                "percent": self.percent,
                "current_doi": self.current_doi,
                "recent": list(self.recent[-8:]),
                "error": self.error,
                "elapsed_sec": elapsed,
                "eta_sec": eta,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "report": summary,
                "failed_dois": summary["failed_dois"] if self.status in {"completed", "failed"} else [],
                "report_text": format_report_text(summary) if self.status == "completed" else "",
            }
            if include_results:
                serialized = []
                for item in self.results:
                    if hasattr(item, "model_dump"):
                        serialized.append(item.model_dump())
                    elif hasattr(item, "dict"):
                        serialized.append(item.dict())
                    else:
                        serialized.append(item)
                data["results"] = serialized
            return data


_jobs: dict[str, JobState] = {}
_jobs_lock = threading.Lock()
_MAX_JOBS = 40


def _prune_jobs() -> None:
    if len(_jobs) <= _MAX_JOBS:
        return
    items = sorted(_jobs.values(), key=lambda j: j.updated_at)
    for job in items:
        if len(_jobs) <= _MAX_JOBS:
            break
        if job.status in {"completed", "failed"}:
            _jobs.pop(job.id, None)


def get_job(job_id: str) -> JobState | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def create_job(
    dois: list[str],
    handle_prefix: str,
    concurrency: int,
    result_factory: Callable[[ArticleMeta, str], Any],
) -> JobState:
    job = JobState(
        id=uuid.uuid4().hex,
        total=len(dois),
        handle_prefix=handle_prefix,
        status="queued",
    )
    with _jobs_lock:
        _prune_jobs()
        _jobs[job.id] = job

    async def runner() -> None:
        job.status = "running"
        job.started_at = time.time()
        job.updated_at = job.started_at
        in_flight: set[str] = set()
        ordered_results: list[Any | None] = [None] * len(dois)
        ordered_metas: list[ArticleMeta | None] = [None] * len(dois)

        def on_progress(event: dict[str, Any]) -> None:
            with job._lock:
                phase = event.get("phase")
                doi = event.get("doi") or ""
                idx = int(event.get("index") or 0)
                if phase == "start":
                    in_flight.add(doi)
                    job.current_doi = doi
                elif phase == "done":
                    meta: ArticleMeta = event["meta"]
                    in_flight.discard(doi)
                    job.done += 1
                    if meta.ok:
                        job.succeeded += 1
                    else:
                        job.failed += 1
                    ordered_results[idx] = result_factory(meta, handle_prefix)
                    ordered_metas[idx] = meta
                    job.recent.append(
                        {
                            "doi": meta.doi,
                            "ok": meta.ok,
                            "title": meta.title or None,
                            "filename": build_filename(meta) if meta.ok else None,
                            "error": meta.error,
                        }
                    )
                    if len(job.recent) > 20:
                        job.recent = job.recent[-20:]
                    job.current_doi = next(iter(in_flight), "")
                job.updated_at = time.time()

        try:
            await extract_many(
                dois,
                concurrency=concurrency,
                progress_cb=on_progress,
            )
            with job._lock:
                final_metas: list[ArticleMeta] = []
                final_results: list[Any] = []
                for i, doi in enumerate(dois):
                    meta = ordered_metas[i] or ArticleMeta(doi=doi, error="Unknown failure")
                    item = ordered_results[i] or result_factory(meta, handle_prefix)
                    final_metas.append(meta)
                    final_results.append(item)
                job.metas = final_metas
                job.results = final_results
                job.status = "completed"
                job.current_doi = ""
                job.finished_at = time.time()
                job.updated_at = job.finished_at
        except Exception as exc:  # noqa: BLE001
            with job._lock:
                job.status = "failed"
                job.error = str(exc)
                job.finished_at = time.time()
                job.updated_at = job.finished_at

    def _thread_main() -> None:
        asyncio.run(runner())

    threading.Thread(target=_thread_main, daemon=True).start()
    return job


def build_job_zip(job: JobState) -> bytes:
    if job.status != "completed":
        raise RuntimeError("Job is not completed")
    buf = io.BytesIO()
    used_names: dict[str, int] = {}
    failed = failed_entries(job.metas)
    elapsed = None
    if job.started_at and job.finished_at:
        elapsed = round(job.finished_at - job.started_at, 1)
    summary = build_summary(
        total=job.total,
        succeeded=job.succeeded,
        failed=job.failed,
        failed_dois=failed,
        elapsed_sec=elapsed,
    )
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for meta in job.metas:
            if not meta.ok:
                continue
            name = build_filename(meta)
            count = used_names.get(name, 0)
            used_names[name] = count + 1
            if count:
                stem = name[:-6] if name.endswith(".redif") else name
                name = f"{stem}_{count + 1}.redif"
            zf.writestr(name, to_redif(meta, handle_prefix=job.handle_prefix))

        # Always include final report files
        zf.writestr("_conversion_report.txt", format_report_text(summary))
        zf.writestr("_failed.csv", format_failed_csv(failed))
    return buf.getvalue()
