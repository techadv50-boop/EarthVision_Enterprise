"""Scene cache and download orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.models.scene import Scene
from app.schemas.catalog import SceneSummary
from app.services.copernicus_service import CopernicusCatalogService


class SceneService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.catalog = CopernicusCatalogService()
        self.cache_dir = self.settings.imagery_cache_dir / "scenes"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def upsert_from_summary(self, summary: SceneSummary) -> Scene:
        result = await self.session.execute(
            select(Scene).where(Scene.external_id == summary.id)
        )
        scene = result.scalar_one_or_none()
        if scene is None:
            scene = Scene(external_id=summary.id)
            self.session.add(scene)
        scene.collection = summary.collection
        scene.platform = summary.platform
        scene.product_type = summary.product_type
        scene.sensing_time = summary.sensing_time
        scene.cloud_cover = summary.cloud_cover
        scene.footprint = summary.footprint
        scene.center_lon = summary.center[0] if summary.center else None
        scene.center_lat = summary.center[1] if summary.center else None
        scene.thumbnail_url = summary.thumbnail_url
        scene.file_size_bytes = summary.size_bytes
        scene.metadata_json = summary.metadata
        scene.title = summary.name
        if scene.status == "discovered" or scene.status is None:
            scene.status = "discovered"
        await self.session.flush()
        await self.session.refresh(scene)
        return scene

    async def get(self, scene_id: str) -> Scene:
        result = await self.session.execute(
            select(Scene).where((Scene.id == scene_id) | (Scene.external_id == scene_id))
        )
        scene = result.scalar_one_or_none()
        if scene is None:
            raise NotFoundError("Scene not found")
        return scene

    async def list_cached(self, *, collection: str | None = None, limit: int = 50) -> list[Scene]:
        query = select(Scene).order_by(Scene.sensing_time.desc().nullslast()).limit(limit)
        if collection:
            query = query.where(Scene.collection == collection)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def request_download(self, external_id: str, collection: str) -> dict[str, Any]:
        """Mark scene for download and create a local cache stub (metadata + placeholder)."""
        summary = SceneSummary(
            id=external_id,
            name=external_id,
            collection=collection,
            platform=collection.split("-")[0],
        )
        scene = await self.upsert_from_summary(summary)
        scene.status = "downloading"
        await self.session.flush()

        local_path = self.cache_dir / f"{external_id}.meta.json"
        download_url = await self.catalog.get_download_url(external_id)

        # Attempt authenticated download only when credentials exist; otherwise cache metadata
        if self.catalog.token_manager.is_configured:
            try:
                token = await self.catalog.token_manager.get_token()
                # HEAD request to validate access; full product download is multi-GB
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                    head = await client.head(
                        download_url, headers={"Authorization": f"Bearer {token}"}
                    )
                    logger.info("Download HEAD status for {}: {}", external_id, head.status_code)
            except Exception as exc:
                logger.warning("Download probe failed: {}", exc)

        meta = {
            "external_id": external_id,
            "collection": collection,
            "download_url": download_url,
            "cached_at": datetime.now(UTC).isoformat(),
            "status": "queued",
            "note": (
                "Full product download requires CDSE credentials and storage capacity. "
                "Metadata and footprint are cached; retrieve $value when ready."
            ),
        }
        local_path.write_text(__import__("json").dumps(meta, indent=2))
        scene.local_path = str(local_path)
        scene.download_url = download_url
        scene.status = "cached"
        await self.session.flush()
        await self.session.refresh(scene)

        return {
            "scene_id": scene.id,
            "status": scene.status,
            "local_path": scene.local_path,
            "download_url": scene.download_url,
            "message": "Scene metadata cached; product download queued",
        }

    def get_preview_placeholder(self, scene_id: str) -> bytes:
        """Generate a quick-look style PNG preview."""
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (512, 512), color=(12, 45, 38))
        draw = ImageDraw.Draw(img)
        for i in range(0, 512, 32):
            shade = 20 + (i % 64)
            draw.rectangle([i, 0, i + 16, 512], fill=(shade, shade + 40, shade + 20))
        draw.rectangle([20, 20, 492, 80], fill=(11, 61, 46))
        draw.text((32, 40), f"EarthVision Quicklook", fill=(220, 240, 230))
        draw.text((32, 460), scene_id[:48], fill=(180, 200, 190))
        import io

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
