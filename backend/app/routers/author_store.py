"""Article store: upload papers under each author-database journal and download later."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import require_service
from app.core.security import verify_password
from app.database.session import get_db
from app.models.citation import AuthorDbJournal, AuthorStoreFile
from app.models.user import User
from app.schemas.author_db import AuthorStoreDownloadIn, AuthorStoreFileOut, AuthorStoreJournalOut
from app.routers.author_db import _ensure_author_catalog

router = APIRouter(prefix="/author-articles/store", tags=["Author article store"])

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(require_service("authors"))]

ALLOWED_SUFFIXES = {".pdf", ".doc", ".docx", ".txt", ".rtf"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _store_root() -> Path:
    root = get_settings().upload_dir / "author-store"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_filename(name: str) -> str:
    base = Path(name or "article").name
    cleaned = _SAFE_NAME.sub("_", base).strip("._") or "article"
    return cleaned[:180]


def _journal_key(row: AuthorDbJournal) -> str:
    return (row.abbreviation or row.name or "").strip()


async def _resolve_journal(db: AsyncSession, key: str) -> AuthorDbJournal:
    catalog = await _ensure_author_catalog(db)
    needle = (key or "").strip().lower()
    if not needle:
        raise HTTPException(status_code=404, detail="Journal not found")
    for row in catalog:
        abbr = (row.abbreviation or "").strip().lower()
        name = (row.name or "").strip().lower()
        if needle in {abbr, name}:
            return row
    raise HTTPException(status_code=404, detail="Journal not found")


def _file_out(row: AuthorStoreFile) -> AuthorStoreFileOut:
    return AuthorStoreFileOut(
        id=row.id,
        journal_key=row.journal_key,
        journal_name=row.journal_name,
        original_name=row.original_name,
        content_type=row.content_type or "",
        size_bytes=int(row.size_bytes or 0),
        created_at=row.created_at,
    )


def _require_admin_password(user: User, password: str) -> None:
    if not user.is_full_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can download stored articles. Sign in as admin and enter the admin password.",
        )
    text = (password or "").strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Enter the admin password to download this article.",
        )
    if not verify_password(text, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="That password is not correct.",
        )


@router.get("/journals", response_model=list[AuthorStoreJournalOut])
async def list_store_journals(db: Db, user: CurrentUser):
    catalog = await _ensure_author_catalog(db)
    counts = {
        str(key): int(total)
        for key, total in (
            await db.execute(
                select(AuthorStoreFile.journal_key, func.count(AuthorStoreFile.id)).group_by(
                    AuthorStoreFile.journal_key
                )
            )
        ).all()
    }
    out: list[AuthorStoreJournalOut] = []
    for row in catalog:
        key = _journal_key(row)
        if not key:
            continue
        out.append(
            AuthorStoreJournalOut(
                key=key,
                name=row.name,
                abbreviation=row.abbreviation or "",
                file_count=counts.get(key, 0),
            )
        )
    return out


@router.get("/{journal_key}/files", response_model=list[AuthorStoreFileOut])
async def list_store_files(journal_key: str, db: Db, user: CurrentUser):
    journal = await _resolve_journal(db, journal_key)
    key = _journal_key(journal)
    rows = list(
        (
            await db.execute(
                select(AuthorStoreFile)
                .where(AuthorStoreFile.journal_key == key)
                .order_by(AuthorStoreFile.created_at.desc(), AuthorStoreFile.id.desc())
            )
        ).scalars().all()
    )
    return [_file_out(row) for row in rows]


@router.post("/{journal_key}/files", response_model=AuthorStoreFileOut, status_code=status.HTTP_201_CREATED)
async def upload_store_file(
    journal_key: str,
    db: Db,
    user: CurrentUser,
    file: UploadFile = File(...),
):
    journal = await _resolve_journal(db, journal_key)
    original = file.filename or "article.pdf"
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="Upload a PDF, Word, RTF, or text article file.",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="That file is empty.")
    limit = get_settings().max_upload_size_mb * 1024 * 1024
    if len(data) > limit:
        raise HTTPException(status_code=400, detail="That file is too large to store.")
    key = _journal_key(journal)
    folder = _store_root() / _safe_filename(key or "journal")
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    stored_name = f"{stamp}_{_safe_filename(original)}"
    dest = folder / stored_name
    dest.write_bytes(data)
    row = AuthorStoreFile(
        journal_key=key,
        journal_name=journal.name,
        original_name=Path(original).name,
        stored_path=str(dest),
        content_type=file.content_type or "",
        size_bytes=len(data),
        uploaded_by=user.id,
    )
    db.add(row)
    await db.flush()
    return _file_out(row)


@router.post("/files/{file_id}/download")
async def download_store_file(
    file_id: int,
    body: AuthorStoreDownloadIn,
    db: Db,
    user: CurrentUser,
):
    _require_admin_password(user, body.password)
    row = await db.get(AuthorStoreFile, file_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Stored article not found")
    path = Path(row.stored_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The stored file is no longer on disk.")
    filename = row.original_name or path.name
    return FileResponse(
        path,
        media_type=row.content_type or "application/octet-stream",
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
