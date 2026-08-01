"""CRUD + seed for global satellite providers."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.satellite_provider import SatelliteProvider
from app.schemas.satellite_provider import (
    SatelliteProviderAdmin,
    SatelliteProviderCreate,
    SatelliteProviderUpdate,
)

BUILTIN_SATELLITES: list[dict[str, object]] = [
    {
        "name": "SENTINEL-2",
        "label": "Sentinel-2",
        "collection_id": "SENTINEL-2",
        "sort_order": 10,
    },
    {
        "name": "SENTINEL-1",
        "label": "Sentinel-1",
        "collection_id": "SENTINEL-1",
        "sort_order": 20,
    },
    {
        "name": "LANDSAT-9",
        "label": "Landsat-9",
        "collection_id": "LANDSAT-9",
        "sort_order": 30,
    },
    {
        "name": "LANDSAT-8",
        "label": "Landsat-8",
        "collection_id": "LANDSAT-8",
        "sort_order": 40,
    },
]


def _normalize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip().upper()).strip("-")
    if len(cleaned) < 2:
        raise ValidationError("Satellite name must contain letters or numbers")
    return cleaned[:64]


def to_admin(row: SatelliteProvider) -> SatelliteProviderAdmin:
    return SatelliteProviderAdmin(
        id=row.id,
        name=row.name,
        label=row.label,
        collection_id=row.collection_id,
        enabled=row.enabled,
        is_builtin=row.is_builtin,
        sort_order=row.sort_order,
        api_base_url=row.api_base_url,
        token_url=row.token_url,
        client_id=row.client_id,
        auth_username=row.auth_username,
        has_password=bool(row.auth_password),
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SatelliteProviderService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def ensure_builtins(self) -> None:
        """Seed built-in satellites once; keep existing rows intact."""
        settings = get_settings()
        result = await self.db.execute(select(SatelliteProvider.name))
        existing = {row[0] for row in result.all()}
        created = False
        for item in BUILTIN_SATELLITES:
            name = str(item["name"])
            if name in existing:
                continue
            self.db.add(
                SatelliteProvider(
                    name=name,
                    label=str(item["label"]),
                    collection_id=str(item["collection_id"]),
                    api_base_url=settings.copernicus_catalog_url,
                    token_url=settings.copernicus_token_url,
                    client_id=settings.copernicus_client_id,
                    auth_username=settings.copernicus_username or None,
                    auth_password=settings.copernicus_password or None,
                    enabled=True,
                    is_builtin=True,
                    sort_order=int(item["sort_order"]),
                )
            )
            created = True
        if created:
            await self.db.commit()

    async def list_enabled(self) -> list[SatelliteProvider]:
        result = await self.db.execute(
            select(SatelliteProvider)
            .where(SatelliteProvider.enabled.is_(True))
            .order_by(SatelliteProvider.sort_order.asc(), SatelliteProvider.label.asc())
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[SatelliteProvider]:
        result = await self.db.execute(
            select(SatelliteProvider).order_by(
                SatelliteProvider.sort_order.asc(), SatelliteProvider.label.asc()
            )
        )
        return list(result.scalars().all())

    async def get(self, provider_id: str) -> SatelliteProvider:
        row = await self.db.get(SatelliteProvider, provider_id)
        if row is None:
            raise NotFoundError("Satellite provider not found")
        return row

    async def create(self, data: SatelliteProviderCreate) -> SatelliteProvider:
        name = _normalize_name(data.name)
        existing = await self.db.execute(
            select(SatelliteProvider).where(SatelliteProvider.name == name)
        )
        if existing.scalar_one_or_none() is not None:
            raise ConflictError(f"Satellite '{name}' already exists")
        row = SatelliteProvider(
            name=name,
            label=data.label.strip(),
            collection_id=data.collection_id.strip(),
            api_base_url=(data.api_base_url or None),
            token_url=(data.token_url or None),
            client_id=(data.client_id or None),
            auth_username=(data.auth_username or None),
            auth_password=(data.auth_password or None),
            notes=data.notes,
            enabled=data.enabled,
            is_builtin=False,
            sort_order=data.sort_order,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def update(
        self, provider_id: str, data: SatelliteProviderUpdate
    ) -> SatelliteProvider:
        row = await self.get(provider_id)
        payload = data.model_dump(exclude_unset=True)
        if "auth_password" in payload and not payload["auth_password"]:
            # Empty string means "leave unchanged"
            payload.pop("auth_password")
        for key, value in payload.items():
            if key in {"label", "collection_id"} and isinstance(value, str):
                value = value.strip()
            setattr(row, key, value)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def delete(self, provider_id: str) -> None:
        row = await self.get(provider_id)
        if row.is_builtin:
            raise ValidationError("Built-in satellites cannot be deleted (disable instead)")
        await self.db.delete(row)
        await self.db.commit()
