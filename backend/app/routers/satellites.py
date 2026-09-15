"""SatPass satellite / TLE routes.

Public endpoints (no auth) to store TLE sets and to look them up from
Celestrak by name or NORAD catalog number, so users never have to hand-type
a TLE. Orbit propagation itself is done client-side (SGP4 in the browser).
"""

from typing import Annotated, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database.session import get_db
from app.models.satellite import Satellite
from app.models.user import User
from app.schemas.satellite import SatelliteCreate, SatelliteResponse, TleResult

router = APIRouter(prefix="/satellites", tags=["SatPass"])

CELESTRAK_GP_URL = "https://celestrak.org/NORAD/elements/gp.php"


def _norad_from_line1(line1: str) -> Optional[int]:
    """Satellite catalog number lives in columns 3-7 of TLE line 1."""
    try:
        return int(line1[2:7])
    except (ValueError, IndexError):
        return None


def _parse_tle_text(text: str) -> list[TleResult]:
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    results: list[TleResult] = []
    i = 0
    while i < len(lines):
        # A well-formed record is: name, "1 ...", "2 ...".
        if lines[i].startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
            # No name line present.
            line1, line2 = lines[i], lines[i + 1]
            results.append(
                TleResult(name=f"NORAD {_norad_from_line1(line1)}", norad_id=_norad_from_line1(line1), line1=line1, line2=line2)
            )
            i += 2
            continue
        if i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            name, line1, line2 = lines[i].strip(), lines[i + 1], lines[i + 2]
            results.append(
                TleResult(name=name, norad_id=_norad_from_line1(line1), line1=line1, line2=line2)
            )
            i += 3
            continue
        i += 1
    return results


@router.get("/fetch", response_model=list[TleResult])
async def fetch_tle(
    _user: Annotated[User, Depends(get_current_user)],
    q: str = Query(min_length=1, description="Satellite name or NORAD catalog number"),
):
    """Look up current TLE(s) from Celestrak by NORAD id (digits) or name."""
    query = q.strip()
    params = {"FORMAT": "TLE"}
    if query.isdigit():
        params["CATNR"] = query
    else:
        params["NAME"] = query

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(CELESTRAK_GP_URL, params=params)
            resp.raise_for_status()
            text = resp.text
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Celestrak lookup failed: {exc}") from exc

    if "No GP data found" in text or not text.strip():
        raise HTTPException(status_code=404, detail=f"No satellite found for '{query}'.")

    results = _parse_tle_text(text)
    if not results:
        raise HTTPException(status_code=404, detail=f"No usable TLE found for '{query}'.")
    return results


@router.get("", response_model=list[SatelliteResponse])
async def list_satellites(
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rows = await db.execute(select(Satellite).order_by(Satellite.created_at))
    return list(rows.scalars().all())


@router.post("", response_model=SatelliteResponse, status_code=201)
async def add_satellite(
    payload: SatelliteCreate,
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    norad = payload.norad_id or _norad_from_line1(payload.line1)
    satellite = Satellite(
        name=payload.name,
        norad_id=norad,
        tle_line1=payload.line1,
        tle_line2=payload.line2,
        color=payload.color,
    )
    db.add(satellite)
    await db.flush()
    await db.refresh(satellite)
    return satellite


@router.delete("/{satellite_id}", status_code=204)
async def delete_satellite(
    satellite_id: int,
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = await db.get(Satellite, satellite_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Satellite not found")
    await db.delete(row)
    return None
