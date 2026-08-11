"""FastAPI application: DOI → ReDIF converter."""

from __future__ import annotations

import io
import zipfile
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .extractor import dois_from_xlsx_bytes, extract_many, parse_doi_list
from .paths import app_root, static_dir
from .redif import DEFAULT_REPEC_HANDLE_PREFIX, build_filename, to_redif

ROOT = app_root()
STATIC = static_dir()

app = FastAPI(
    title="DOI → ReDIF Converter",
    description="Upload or paste DOIs, extract article metadata, and export ReDIF files.",
    version="1.0.0",
)


class ConvertRequest(BaseModel):
    dois: list[str] = Field(default_factory=list)
    text: str = ""
    handle_prefix: str = DEFAULT_REPEC_HANDLE_PREFIX
    concurrency: int = 5


class AuthorOut(BaseModel):
    name: str
    email: str | None = None
    workplace: str | None = None


class ResultOut(BaseModel):
    doi: str
    ok: bool
    filename: str | None = None
    title: str | None = None
    journal: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    year: str | None = None
    month: str | None = None
    authors: list[AuthorOut] = Field(default_factory=list)
    source: str | None = None
    error: str | None = None
    redif: str | None = None


class ConvertResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[ResultOut]


def _collect_dois(dois: list[str] | None, text: str | None) -> list[str]:
    collected: list[str] = []
    seen: set[str] = set()
    for item in list(dois or []) + parse_doi_list(text or ""):
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        collected.append(item)
    return collected


def _to_result(meta, handle_prefix: str, include_redif: bool = True) -> ResultOut:
    filename = build_filename(meta) if meta.ok else None
    redif = to_redif(meta, handle_prefix=handle_prefix) if meta.ok and include_redif else None
    return ResultOut(
        doi=meta.doi,
        ok=meta.ok,
        filename=filename,
        title=meta.title or None,
        journal=meta.journal or None,
        volume=meta.volume or None,
        issue=meta.issue or None,
        pages=meta.pages or None,
        year=meta.year or None,
        month=meta.month or None,
        authors=[
            AuthorOut(name=a.name, email=a.email, workplace=a.workplace) for a in meta.authors
        ],
        source=meta.source or None,
        error=meta.error,
        redif=redif,
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/parse-upload")
async def parse_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    raw = await file.read()
    name = (file.filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        dois = dois_from_xlsx_bytes(raw)
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="ignore")
        dois = parse_doi_list(text)
    return {"count": len(dois), "dois": dois}


@app.post("/api/convert", response_model=ConvertResponse)
async def convert(payload: ConvertRequest) -> ConvertResponse:
    dois = _collect_dois(payload.dois, payload.text)
    if not dois:
        raise HTTPException(status_code=400, detail="No valid DOIs provided")
    if len(dois) > 1000:
        raise HTTPException(status_code=400, detail="Maximum 1000 DOIs per request")

    concurrency = max(1, min(payload.concurrency or 5, 10))
    metas = await extract_many(dois, concurrency=concurrency)
    results = [_to_result(m, payload.handle_prefix) for m in metas]
    succeeded = sum(1 for r in results if r.ok)
    return ConvertResponse(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
    )


@app.post("/api/convert-upload", response_model=ConvertResponse)
async def convert_upload(
    file: UploadFile = File(...),
    handle_prefix: str = Form(DEFAULT_REPEC_HANDLE_PREFIX),
    concurrency: int = Form(5),
) -> ConvertResponse:
    raw = await file.read()
    name = (file.filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        dois = dois_from_xlsx_bytes(raw)
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="ignore")
        dois = parse_doi_list(text)

    if not dois:
        raise HTTPException(status_code=400, detail="No valid DOIs found in upload")
    if len(dois) > 1000:
        raise HTTPException(status_code=400, detail="Maximum 1000 DOIs per request")

    concurrency = max(1, min(concurrency or 5, 10))
    metas = await extract_many(dois, concurrency=concurrency)
    results = [_to_result(m, handle_prefix) for m in metas]
    succeeded = sum(1 for r in results if r.ok)
    return ConvertResponse(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
    )


@app.post("/api/export-zip")
async def export_zip(payload: ConvertRequest) -> StreamingResponse:
    dois = _collect_dois(payload.dois, payload.text)
    if not dois:
        raise HTTPException(status_code=400, detail="No valid DOIs provided")

    concurrency = max(1, min(payload.concurrency or 5, 10))
    metas = await extract_many(dois, concurrency=concurrency)

    buf = io.BytesIO()
    used_names: dict[str, int] = {}
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for meta in metas:
            if not meta.ok:
                continue
            name = build_filename(meta)
            count = used_names.get(name, 0)
            used_names[name] = count + 1
            if count:
                stem = name[:-6] if name.endswith(".redif") else name
                name = f"{stem}_{count + 1}.redif"
            zf.writestr(name, to_redif(meta, handle_prefix=payload.handle_prefix))

        # include a manifest of failures
        failures = [m for m in metas if not m.ok]
        if failures:
            lines = ["doi,error"]
            for m in failures:
                err = (m.error or "failed").replace('"', "'")
                lines.append(f'"{m.doi}","{err}"')
            zf.writestr("_failed.csv", "\n".join(lines) + "\n")

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="redif-export.zip"'},
    )


@app.get("/")
async def index() -> FileResponse:
    index_path = STATIC / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
