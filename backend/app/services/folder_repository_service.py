"""CRUD + Bearer proxy for relay.xdgen.com folder repositories."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.models.folder_repository import FolderRepository
from app.schemas.folder_repository import (
    ALLOWED_RELAY_HOST,
    FolderFileEntry,
    FolderRepositoryAdmin,
    FolderRepositoryCreate,
    FolderRepositoryUpdate,
    validate_relay_repository_url,
)

RELAY_TIMEOUT = httpx.Timeout(20.0, read=120.0, write=30.0, pool=10.0)


def to_admin(row: FolderRepository) -> FolderRepositoryAdmin:
    return FolderRepositoryAdmin(
        id=row.id,
        label=row.label,
        repository_url=row.repository_url,
        enabled=row.enabled,
        sort_order=row.sort_order,
        has_api_key=bool(row.api_key),
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key.strip()}"}


def _extract_dates(payload: Any) -> list[str]:
    """Normalize relay date payloads into YYYY-MM-DD strings."""
    dates: list[str] = []

    def add(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            text = value.strip()[:10]
            if len(text) >= 8 and text not in dates:
                dates.append(text)
            return
        if isinstance(value, dict):
            for key in ("date", "day", "name", "label", "value"):
                if key in value:
                    add(value[key])
                    return

    if isinstance(payload, list):
        for item in payload:
            add(item)
    elif isinstance(payload, dict):
        for key in ("dates", "items", "days", "data", "results"):
            if key in payload and isinstance(payload[key], list):
                for item in payload[key]:
                    add(item)
                break
        else:
            add(payload)
    return dates


def _file_path(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry.strip() or None
    if not isinstance(entry, dict):
        return None
    for key in ("path", "relative_path", "name", "filename", "file"):
        val = entry.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _extract_files(payload: Any) -> list[FolderFileEntry]:
    items: list[Any]
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = []
        for key in ("files", "items", "data", "results", "objects"):
            if isinstance(payload.get(key), list):
                items = payload[key]
                break
        if not items and payload:
            items = [payload]
    else:
        items = []

    out: list[FolderFileEntry] = []
    for item in items:
        path = _file_path(item)
        if not path:
            continue
        name = None
        size = None
        if isinstance(item, dict):
            name = (
                item.get("name")
                or item.get("filename")
                or path.rsplit("/", 1)[-1]
            )
            raw_size = item.get("size") or item.get("bytes")
            if isinstance(raw_size, (int, float)):
                size = int(raw_size)
        else:
            name = path.rsplit("/", 1)[-1]
        out.append(
            FolderFileEntry(
                path=path,
                name=str(name) if name else path,
                size=size,
                raw=item if isinstance(item, (dict, list, str, int, float)) else None,
            )
        )
    return out


class FolderRepositoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_enabled(self) -> list[FolderRepository]:
        result = await self.db.execute(
            select(FolderRepository)
            .where(FolderRepository.enabled.is_(True))
            .order_by(FolderRepository.sort_order.asc(), FolderRepository.label.asc())
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[FolderRepository]:
        result = await self.db.execute(
            select(FolderRepository).order_by(
                FolderRepository.sort_order.asc(), FolderRepository.label.asc()
            )
        )
        return list(result.scalars().all())

    async def get(self, repo_id: str) -> FolderRepository:
        row = await self.db.get(FolderRepository, repo_id)
        if row is None:
            raise NotFoundError("Folder repository not found")
        return row

    async def create(self, data: FolderRepositoryCreate) -> FolderRepository:
        url = validate_relay_repository_url(data.repository_url)
        existing = await self.db.execute(
            select(FolderRepository).where(FolderRepository.repository_url == url)
        )
        if existing.scalar_one_or_none() is not None:
            raise ConflictError("A folder repository with this address already exists")
        row = FolderRepository(
            label=data.label.strip(),
            repository_url=url,
            api_key=data.api_key.strip(),
            notes=data.notes,
            enabled=data.enabled,
            sort_order=data.sort_order,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def update(
        self, repo_id: str, data: FolderRepositoryUpdate
    ) -> FolderRepository:
        row = await self.get(repo_id)
        payload = data.model_dump(exclude_unset=True)
        if "api_key" in payload and not payload["api_key"]:
            payload.pop("api_key")
        if "repository_url" in payload and payload["repository_url"]:
            payload["repository_url"] = validate_relay_repository_url(
                payload["repository_url"]
            )
        for key, value in payload.items():
            if key == "label" and isinstance(value, str):
                value = value.strip()
            setattr(row, key, value)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def delete(self, repo_id: str) -> None:
        row = await self.get(repo_id)
        await self.db.delete(row)
        await self.db.commit()

    async def _relay_get_json(self, row: FolderRepository, url: str) -> Any:
        if ALLOWED_RELAY_HOST not in url:
            raise ValidationError("Refusing non-relay URL")
        try:
            async with httpx.AsyncClient(timeout=RELAY_TIMEOUT, follow_redirects=True) as client:
                response = await client.get(url, headers=_auth_headers(row.api_key))
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"Relay request failed: {exc}") from exc

        if response.status_code == 401:
            raise UnauthorizedError(
                "Unauthorized (401): API key does not belong to this folder repository"
            )
        if response.status_code >= 400:
            raise ExternalServiceError(
                f"Relay returned HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            return response.json()
        except Exception:
            # Some relays may return a plain list encoded as text lines
            text = response.text.strip()
            if not text:
                return []
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            return lines

    async def list_dates(self, repo_id: str) -> tuple[list[str], Any]:
        row = await self.get(repo_id)
        if not row.enabled:
            raise NotFoundError("Folder repository is disabled")
        payload = await self._relay_get_json(row, row.repository_url)
        return _extract_dates(payload), payload

    async def list_files(self, repo_id: str, date: str) -> tuple[list[FolderFileEntry], Any]:
        row = await self.get(repo_id)
        if not row.enabled:
            raise NotFoundError("Folder repository is disabled")
        day = (date or "").strip()[:10]
        if len(day) < 8:
            raise ValidationError("date must be YYYY-MM-DD")
        url = f"{row.repository_url}/files?date={quote(day)}"
        payload = await self._relay_get_json(row, url)
        return _extract_files(payload), payload

    async def download_file(
        self, repo_id: str, *, date: str, path: str
    ) -> tuple[bytes, str, str | None]:
        """Return (content, filename, content_type)."""
        row = await self.get(repo_id)
        if not row.enabled:
            raise NotFoundError("Folder repository is disabled")
        day = (date or "").strip()[:10]
        file_path = (path or "").strip()
        if len(day) < 8:
            raise ValidationError("date must be YYYY-MM-DD")
        if not file_path:
            raise ValidationError("path is required")
        url = (
            f"{row.repository_url}/file?date={quote(day)}"
            f"&path={quote(file_path, safe='/')}"
        )
        if ALLOWED_RELAY_HOST not in url:
            raise ValidationError("Refusing non-relay URL")
        try:
            async with httpx.AsyncClient(timeout=RELAY_TIMEOUT, follow_redirects=True) as client:
                response = await client.get(url, headers=_auth_headers(row.api_key))
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"Relay download failed: {exc}") from exc

        if response.status_code == 401:
            raise UnauthorizedError(
                "Unauthorized (401): API key does not belong to this folder repository"
            )
        if response.status_code >= 400:
            raise ExternalServiceError(
                f"Relay returned HTTP {response.status_code}: {response.text[:300]}"
            )
        filename = file_path.rsplit("/", 1)[-1] or "download.bin"
        content_type = response.headers.get("content-type")
        return response.content, filename, content_type
