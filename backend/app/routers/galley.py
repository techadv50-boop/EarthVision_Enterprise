"""Galley composition desk: journals, Word proofs, and equation OCR.

Accounts are the Citation Assistant users. There is no second login.
"""

from __future__ import annotations

import base64
import copy
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.core.dependencies import require_full_admin, require_service
from app.database.session import get_db
from app.models.galley import GalleyJournal, GalleyProof, GalleySetting
from app.models.user import User

router = APIRouter(prefix="/galley", tags=["Galley composition"])

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(require_service("galley"))]
CitationAdmin = Annotated[User, Depends(require_full_admin)]


class OcrBody(BaseModel):
    dataUrl: str


def _owner_label(user: Optional[User], owner_id: int) -> tuple[str, str]:
    if user is None:
        return f"User {owner_id}", ""
    name = (user.full_name or user.username or "").strip() or f"User {owner_id}"
    email = (user.email or "").strip()
    return name, email


def _record(row: GalleyProof) -> dict[str, Any]:
    name, email = _owner_label(row.owner, row.owner_id)
    return {
        "galley": row.data,
        "ownerId": str(row.owner_id),
        "ownerName": name,
        "ownerEmail": email,
    }


@router.get("/settings/open-access")
async def get_open_access(_user: CurrentUser, db: Db) -> dict[str, Any]:
    row = await db.get(GalleySetting, "openAccess")
    return {"icon": row.value if row else None}


@router.put("/settings/open-access")
async def put_open_access(body: dict[str, Any], _admin: CitationAdmin, db: Db) -> dict[str, bool]:
    row = await db.get(GalleySetting, "openAccess")
    if row is None:
        db.add(GalleySetting(key="openAccess", value=body.get("icon")))
    else:
        row.value = body.get("icon")
        flag_modified(row, "value")
    return {"ok": True}


@router.get("/journals")
async def list_journals(_user: CurrentUser, db: Db) -> list[dict[str, Any]]:
    result = await db.execute(select(GalleyJournal))
    return [row.data for row in result.scalars().all()]


@router.post("/journals")
async def save_journal(body: dict[str, Any], _admin: CitationAdmin, db: Db) -> dict[str, Any]:
    journal_id = str(body.get("id") or os.urandom(8).hex())
    payload = copy.deepcopy(body)
    payload["id"] = journal_id
    row = await db.get(GalleyJournal, journal_id)
    if row is None:
        db.add(GalleyJournal(id=journal_id, data=payload))
    else:
        row.data = payload
        flag_modified(row, "data")
    return payload


@router.delete("/journals/{journal_id}")
async def delete_journal(journal_id: str, _admin: CitationAdmin, db: Db) -> dict[str, bool]:
    row = await db.get(GalleyJournal, journal_id)
    if row is not None:
        await db.delete(row)
    return {"ok": True}


@router.get("/galleys")
async def list_galleys(user: CurrentUser, db: Db) -> list[dict[str, Any]]:
    query = (
        select(GalleyProof)
        .options(selectinload(GalleyProof.owner))
        .order_by(GalleyProof.updated_at.desc())
    )
    if not user.is_full_admin():
        query = query.where(GalleyProof.owner_id == user.id)
    result = await db.execute(query)
    return [_record(row) for row in result.scalars().all()]


@router.post("/galleys")
async def create_galley(body: dict[str, Any], user: CurrentUser, db: Db) -> dict[str, Any]:
    galley_id = str(body.get("id") or os.urandom(8).hex())
    payload = copy.deepcopy(body)
    payload["id"] = galley_id
    payload["updatedAt"] = int(time.time() * 1000)
    db.add(
        GalleyProof(
            id=galley_id,
            owner_id=user.id,
            data=payload,
            updated_at=payload["updatedAt"],
        )
    )
    return payload


@router.put("/galleys/{galley_id}")
async def update_galley(
    galley_id: str, body: dict[str, Any], user: CurrentUser, db: Db
) -> dict[str, Any]:
    row = await db.get(GalleyProof, galley_id)
    if row is None:
        raise HTTPException(404, "Galley not found")
    if not user.is_full_admin() and row.owner_id != user.id:
        raise HTTPException(403, "You can edit only your own galley")
    body["id"] = galley_id
    body["updatedAt"] = int(time.time() * 1000)
    payload = copy.deepcopy(body)
    row.data = payload
    row.updated_at = payload["updatedAt"]
    flag_modified(row, "data")
    return payload


@router.delete("/galleys/{galley_id}")
async def delete_galley(galley_id: str, _admin: CitationAdmin, db: Db) -> dict[str, bool]:
    row = await db.get(GalleyProof, galley_id)
    if row is not None:
        await db.delete(row)
    return {"ok": True}


@router.post("/ocr")
async def ocr(body: OcrBody, _user: CurrentUser) -> dict[str, str]:
    raw = body.dataUrl.split(",", 1)[-1]
    try:
        image = base64.b64decode(raw)
    except Exception as exc:
        raise HTTPException(400, "That image could not be read") from exc
    suffix = ".png" if "image/png" in body.dataUrl else ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(image)
        path = handle.name
    try:
        result = subprocess.run(
            ["tesseract", path, "stdout", "--psm", "6"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise HTTPException(503, "Equation reading is not available on this computer") from exc
    finally:
        Path(path).unlink(missing_ok=True)
    if result.returncode != 0:
        raise HTTPException(422, result.stderr.strip() or "The equation image could not be read")
    return {"text": result.stdout.strip()}
