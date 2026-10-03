"""HTTP API for WebCrawler Enterprise v1.4.2 (admin and user accounts)."""

from __future__ import annotations

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_user
from app.models.user import User
from app.services.webcrawler_runtime import session_for, unpack_scan_zip

router = APIRouter(prefix="/webcrawler", tags=["Web crawler"])
CurrentUser = Annotated[User, Depends(get_current_user)]


class CrawlStartIn(BaseModel):
    urls: str = Field(..., description="One URL per line")
    light_mode: Optional[bool] = None


class CrawlerSettingsIn(BaseModel):
    crawl_depth: Optional[int] = None
    max_pages_per_site: Optional[int] = None
    download_timeout: Optional[int] = None
    page_workers: Optional[int] = None
    worker_threads: Optional[int] = None
    retry_attempts: Optional[int] = None
    user_agent: Optional[str] = None
    ignore_robots_txt: Optional[bool] = None
    follow_redirects: Optional[bool] = None
    download_complete_site: Optional[bool] = None
    download_all_images: Optional[bool] = None
    contact_scan_only: Optional[bool] = None
    use_playwright_fallback: Optional[bool] = None


class FolderScanIn(BaseModel):
    recursive: bool = True
    use_ocr: bool = True


@router.get("/status")
def crawler_status(user: CurrentUser) -> dict[str, Any]:
    return session_for(user.id).snapshot()


@router.post("/start")
def crawler_start(body: CrawlStartIn, user: CurrentUser) -> dict[str, Any]:
    session = session_for(user.id)
    try:
        session.start(body.urls, light_mode=body.light_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return session.snapshot()


@router.post("/pause")
def crawler_pause(user: CurrentUser) -> dict[str, Any]:
    session = session_for(user.id)
    session.pause()
    return session.snapshot()


@router.post("/resume")
def crawler_resume(user: CurrentUser) -> dict[str, Any]:
    session = session_for(user.id)
    try:
        session.resume()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.snapshot()


@router.post("/stop")
def crawler_stop(user: CurrentUser) -> dict[str, Any]:
    session = session_for(user.id)
    session.stop()
    return session.snapshot()


@router.post("/next-site")
def crawler_next_site(user: CurrentUser) -> dict[str, Any]:
    session = session_for(user.id)
    try:
        session.next_site()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.snapshot()


@router.post("/clear-session")
def crawler_clear_session(user: CurrentUser) -> dict[str, Any]:
    session = session_for(user.id)
    if session.is_busy():
        raise HTTPException(status_code=409, detail="Stop the current job first.")
    session.clear_session()
    return session.snapshot()


@router.patch("/settings")
def crawler_settings(body: CrawlerSettingsIn, user: CurrentUser) -> dict[str, Any]:
    session = session_for(user.id)
    session.save_settings(body.model_dump(exclude_unset=True))
    return session.snapshot()


@router.get("/sites")
def crawler_sites(user: CurrentUser) -> list[dict[str, Any]]:
    return session_for(user.id).list_sites()


@router.get("/sites/{site_id}")
def crawler_site(site_id: int, user: CurrentUser) -> dict[str, Any]:
    detail = session_for(user.id).site_detail(site_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="That crawled website was not found.")
    return detail


@router.post("/scan-folder")
async def crawler_scan_folder(
    user: CurrentUser,
    file: UploadFile = File(...),
    recursive: bool = True,
    use_ocr: bool = True,
) -> dict[str, Any]:
    session = session_for(user.id)
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Upload a zip or a folder of PDF/DOCX/HTML files.")
    folder = unpack_scan_zip(user.id, payload, file.filename or "scan.zip")
    try:
        session.start_folder_scan(str(folder), recursive=recursive, use_ocr=use_ocr)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.snapshot()
