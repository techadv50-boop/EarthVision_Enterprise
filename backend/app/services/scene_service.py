"""Scene download and caching service."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.scene import CachedScene
from app.schemas.imagery import SceneDownloadResponse
from app.services.copernicus_service import CopernicusService, SF_BAY_BOUNDS


class SceneService:
    """Download, synthesize, and cache satellite scenes.

    Synthetic GeoTIFF layout (Sentinel-2 inspired, 6 bands, uint16):
      1 = Blue  (B2)
      2 = Green (B3)
      3 = Red   (B4)
      4 = NIR   (B8)
      5 = SWIR1 (B11)
      6 = SWIR2 (B12)
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    async def download_scene(
        self,
        user_id: int,
        scene_id: str,
        collection: str,
        *,
        footprint_geojson: Optional[str] = None,
        product_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        acquisition_date: Optional[datetime] = None,
        cloud_cover: Optional[float] = None,
    ) -> SceneDownloadResponse:
        result = await self.db.execute(
            select(CachedScene).where(
                CachedScene.user_id == user_id,
                CachedScene.scene_id == scene_id,
            )
        )
        cached = result.scalar_one_or_none()

        if cached and cached.file_path and Path(cached.file_path).exists():
            if footprint_geojson and not cached.footprint_geojson:
                cached.footprint_geojson = footprint_geojson
                await self.db.flush()
            file_size = Path(cached.file_path).stat().st_size
            return SceneDownloadResponse(
                scene_id=scene_id,
                file_path=cached.file_path,
                file_size_bytes=file_size,
                cached=True,
            )

        scene_dir = self.settings.scene_cache_dir / str(user_id) / collection
        scene_dir.mkdir(parents=True, exist_ok=True)
        file_path = scene_dir / f"{scene_id}.tif"

        meta = dict(metadata or {})
        if cached and cached.metadata_json:
            try:
                meta = {**json.loads(cached.metadata_json), **meta}
            except json.JSONDecodeError:
                pass

        resolved_product_id = product_id or meta.get("id") or meta.get("product_id")
        if isinstance(resolved_product_id, str) and not file_path.exists():
            copernicus = CopernicusService(self.db)
            zip_dest = scene_dir / f"{scene_id}.zip"
            downloaded = await copernicus.download_product(
                user_id, resolved_product_id, zip_dest
            )
            if downloaded and downloaded.exists():
                extracted = self._extract_geotiff_from_zip(downloaded, file_path)
                if extracted:
                    file_path = extracted
                    meta["source"] = "cdse"
                    meta["zip_path"] = str(downloaded)
                else:
                    logger.warning(
                        f"Could not extract GeoTIFF from CDSE zip for {scene_id}; generating synthetic"
                    )

        bounds = self._bounds_from_footprint(footprint_geojson or (cached.footprint_geojson if cached else None))

        if not file_path.exists():
            await self._generate_synthetic_geotiff(file_path, scene_id, bounds=bounds)
            meta.setdefault("generated", True)
            meta.setdefault("bands", ["B2", "B3", "B4", "B8", "B11", "B12"])

        file_size = file_path.stat().st_size
        fp_geojson = footprint_geojson or (cached.footprint_geojson if cached else None)
        if not fp_geojson:
            fp_geojson = self._footprint_from_bounds(bounds)

        acq = acquisition_date or (cached.acquisition_date if cached else None) or datetime.now(timezone.utc)
        if acq.tzinfo is None:
            acq = acq.replace(tzinfo=timezone.utc)

        preview_path = self.get_preview_path(str(file_path))

        if cached:
            cached.file_path = str(file_path)
            cached.cached_at = datetime.now(timezone.utc)
            cached.footprint_geojson = fp_geojson
            cached.preview_path = preview_path
            cached.metadata_json = json.dumps(meta)
            if cloud_cover is not None:
                cached.cloud_cover = cloud_cover
            if acquisition_date is not None:
                cached.acquisition_date = acq
        else:
            cached = CachedScene(
                user_id=user_id,
                scene_id=scene_id,
                collection=collection,
                platform=collection.split("-")[0] if "-" in collection else collection,
                acquisition_date=acq,
                cloud_cover=cloud_cover,
                footprint_geojson=fp_geojson,
                file_path=str(file_path),
                preview_path=preview_path,
                metadata_json=json.dumps(meta),
            )
            self.db.add(cached)

        await self.db.flush()

        return SceneDownloadResponse(
            scene_id=scene_id,
            file_path=str(file_path),
            file_size_bytes=file_size,
            cached=False,
        )

    def _extract_geotiff_from_zip(self, zip_path: Path, dest_tif: Path) -> Optional[Path]:
        """Extract the first .tif/.tiff from a product zip into dest_tif."""
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                tif_names = [
                    n
                    for n in zf.namelist()
                    if n.lower().endswith((".tif", ".tiff")) and not n.endswith("/")
                ]
                if not tif_names:
                    return None
                # Prefer 10m / B04-style products when multiple exist
                preferred = sorted(
                    tif_names,
                    key=lambda n: (
                        0 if "10m" in n.lower() else 1,
                        0 if "b04" in n.lower() or "tci" in n.lower() else 1,
                        len(n),
                    ),
                )
                member = preferred[0]
                with zf.open(member) as src, open(dest_tif, "wb") as out:
                    out.write(src.read())
                return dest_tif
        except (zipfile.BadZipFile, OSError) as exc:
            logger.error(f"Zip extraction failed: {exc}")
            return None

    @staticmethod
    def _bounds_from_footprint(footprint_geojson: Optional[str]) -> tuple[float, float, float, float]:
        if footprint_geojson:
            try:
                from shapely.geometry import shape

                data = json.loads(footprint_geojson)
                if data.get("type") == "Feature":
                    geom = shape(data["geometry"])
                elif data.get("type") == "FeatureCollection":
                    geom = shape(data["features"][0]["geometry"])
                else:
                    geom = shape(data)
                return tuple(geom.bounds)  # type: ignore[return-value]
            except Exception:
                pass
        return SF_BAY_BOUNDS

    @staticmethod
    def _footprint_from_bounds(bounds: tuple[float, float, float, float]) -> str:
        west, south, east, north = bounds
        return json.dumps(
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [west, south],
                        [east, south],
                        [east, north],
                        [west, north],
                        [west, south],
                    ]
                ],
            }
        )

    async def _generate_synthetic_geotiff(
        self,
        file_path: Path,
        scene_id: str,
        bounds: tuple[float, float, float, float] = SF_BAY_BOUNDS,
    ) -> None:
        """Generate a 512x512 6-band Sentinel-2-like GeoTIFF with coherent land-cover patterns."""
        try:
            import rasterio
            from rasterio.transform import from_bounds
        except ImportError as exc:
            raise RuntimeError(
                "rasterio is required to generate GeoTIFF scenes. "
                "Install rasterio (and GDAL) before downloading or synthesizing scenes."
            ) from exc

        width, height = 512, 512
        west, south, east, north = bounds
        transform = from_bounds(west, south, east, north, width, height)

        seed = abs(hash(scene_id)) % (2**32)
        rng = np.random.default_rng(seed)

        ys, xs = np.meshgrid(
            np.linspace(0, 1, height, dtype=np.float64),
            np.linspace(0, 1, width, dtype=np.float64),
            indexing="ij",
        )

        # Large-scale terrain / vegetation undulation
        terrain = (
            0.45 * np.sin(2 * np.pi * xs * 3 + seed % 7)
            + 0.35 * np.cos(2 * np.pi * ys * 2.5)
            + 0.20 * np.sin(2 * np.pi * (xs + ys) * 1.5)
        )
        terrain = (terrain - terrain.min()) / (terrain.max() - terrain.min() + 1e-10)

        # Water body: elliptical lake + river corridor
        lake = ((xs - 0.28) / 0.18) ** 2 + ((ys - 0.55) / 0.12) ** 2 < 1.0
        river = np.abs(ys - (0.35 + 0.25 * np.sin(xs * np.pi * 2))) < 0.025
        water = lake | river

        # Urban core + suburban ring
        urban_core = ((xs - 0.72) / 0.12) ** 2 + ((ys - 0.35) / 0.15) ** 2 < 1.0
        suburban = ((xs - 0.72) / 0.22) ** 2 + ((ys - 0.35) / 0.25) ** 2 < 1.0
        urban = urban_core | (suburban & (rng.random((height, width)) > 0.55))

        # Dense vegetation patches (forest / cropland)
        veg_patch = ((xs - 0.45) / 0.25) ** 2 + ((ys - 0.75) / 0.18) ** 2 < 1.0
        vegetation = (terrain > 0.45) & ~water & ~urban
        dense_veg = veg_patch & ~water & ~urban

        # Bare soil / sparse
        bare = ~water & ~urban & ~vegetation & ~dense_veg

        # Reflectance-ish DN values (Sentinel-2 scaled ~0-10000)
        noise = lambda scale: rng.normal(0, scale, (height, width))

        blue = np.full((height, width), 800.0)
        green = np.full((height, width), 900.0)
        red = np.full((height, width), 700.0)
        nir = np.full((height, width), 2000.0)
        swir1 = np.full((height, width), 1500.0)
        swir2 = np.full((height, width), 1200.0)

        # Water: low NIR/SWIR, moderate blue/green
        blue[water] = 1200 + noise(40)[water]
        green[water] = 900 + noise(40)[water]
        red[water] = 400 + noise(30)[water]
        nir[water] = 150 + noise(20)[water]
        swir1[water] = 80 + noise(15)[water]
        swir2[water] = 50 + noise(10)[water]

        # Dense vegetation: high NIR, low red (high NDVI)
        blue[dense_veg] = 400 + 200 * terrain[dense_veg] + noise(50)[dense_veg]
        green[dense_veg] = 700 + 300 * terrain[dense_veg] + noise(60)[dense_veg]
        red[dense_veg] = 300 + 150 * (1 - terrain[dense_veg]) + noise(40)[dense_veg]
        nir[dense_veg] = 3500 + 1500 * terrain[dense_veg] + noise(100)[dense_veg]
        swir1[dense_veg] = 1200 + 400 * terrain[dense_veg] + noise(80)[dense_veg]
        swir2[dense_veg] = 800 + 300 * terrain[dense_veg] + noise(60)[dense_veg]

        # Moderate vegetation
        blue[vegetation] = 500 + 250 * terrain[vegetation] + noise(50)[vegetation]
        green[vegetation] = 800 + 350 * terrain[vegetation] + noise(60)[vegetation]
        red[vegetation] = 500 + 200 * (1 - terrain[vegetation]) + noise(50)[vegetation]
        nir[vegetation] = 2500 + 1200 * terrain[vegetation] + noise(100)[vegetation]
        swir1[vegetation] = 1400 + 500 * terrain[vegetation] + noise(80)[vegetation]
        swir2[vegetation] = 1000 + 400 * terrain[vegetation] + noise(70)[vegetation]

        # Urban: elevated SWIR (high NDBI), moderate NIR
        blue[urban] = 1100 + noise(80)[urban]
        green[urban] = 1050 + noise(80)[urban]
        red[urban] = 1200 + noise(90)[urban]
        nir[urban] = 1800 + noise(100)[urban]
        swir1[urban] = 2800 + noise(120)[urban]
        swir2[urban] = 2400 + noise(110)[urban]
        # Stronger SWIR in urban core
        blue[urban_core] = 1300 + noise(60)[urban_core]
        red[urban_core] = 1400 + noise(70)[urban_core]
        swir1[urban_core] = 3200 + noise(100)[urban_core]
        swir2[urban_core] = 2800 + noise(90)[urban_core]

        # Bare soil
        blue[bare] = 900 + 300 * terrain[bare] + noise(70)[bare]
        green[bare] = 1000 + 300 * terrain[bare] + noise(70)[bare]
        red[bare] = 1100 + 400 * terrain[bare] + noise(80)[bare]
        nir[bare] = 1600 + 400 * terrain[bare] + noise(90)[bare]
        swir1[bare] = 2000 + 500 * terrain[bare] + noise(100)[bare]
        swir2[bare] = 1800 + 400 * terrain[bare] + noise(90)[bare]

        bands = [
            np.clip(blue, 0, 10000).astype(np.uint16),
            np.clip(green, 0, 10000).astype(np.uint16),
            np.clip(red, 0, 10000).astype(np.uint16),
            np.clip(nir, 0, 10000).astype(np.uint16),
            np.clip(swir1, 0, 10000).astype(np.uint16),
            np.clip(swir2, 0, 10000).astype(np.uint16),
        ]

        with rasterio.open(
            file_path,
            "w",
            driver="GTiff",
            height=height,
            width=width,
            count=6,
            dtype=np.uint16,
            crs="EPSG:4326",
            transform=transform,
            compress="deflate",
            tiled=True,
            blockxsize=256,
            blockysize=256,
        ) as dst:
            for i, band in enumerate(bands, 1):
                dst.write(band, i)
                dst.set_band_description(
                    i, ["Blue/B2", "Green/B3", "Red/B4", "NIR/B8", "SWIR1/B11", "SWIR2/B12"][i - 1]
                )

    def get_preview_path(self, file_path: str) -> Optional[str]:
        """Create an RGB PNG preview from bands 3/2/1 (Red/Green/Blue) and return its path."""
        src_path = Path(file_path)
        if not src_path.exists():
            return None

        preview_path = src_path.with_suffix(".preview.png")
        if preview_path.exists() and preview_path.stat().st_mtime >= src_path.stat().st_mtime:
            return str(preview_path)

        try:
            import rasterio
            from PIL import Image
        except ImportError:
            logger.warning("rasterio/Pillow unavailable for preview generation")
            return None

        try:
            with rasterio.open(src_path) as src:
                # Prefer Red/Green/Blue = bands 3,2,1 for 6-band layout; fall back if fewer bands
                if src.count >= 3:
                    r = src.read(3).astype(np.float64)
                    g = src.read(2).astype(np.float64)
                    b = src.read(1).astype(np.float64)
                elif src.count == 1:
                    r = g = b = src.read(1).astype(np.float64)
                else:
                    r = src.read(min(3, src.count)).astype(np.float64)
                    g = src.read(min(2, src.count)).astype(np.float64)
                    b = src.read(1).astype(np.float64)

            def stretch(arr: np.ndarray) -> np.ndarray:
                valid = arr[np.isfinite(arr)]
                if valid.size == 0:
                    return np.zeros_like(arr, dtype=np.uint8)
                lo, hi = np.percentile(valid, (2, 98))
                if hi <= lo:
                    hi = lo + 1
                out = (arr - lo) / (hi - lo)
                return np.clip(out * 255, 0, 255).astype(np.uint8)

            rgb = np.dstack([stretch(r), stretch(g), stretch(b)])
            Image.fromarray(rgb, mode="RGB").save(preview_path, format="PNG")
            return str(preview_path)
        except Exception as exc:
            logger.error(f"Preview generation failed for {file_path}: {exc}")
            return None

    async def get_cached_scenes(self, user_id: int) -> list[CachedScene]:
        result = await self.db.execute(
            select(CachedScene)
            .where(CachedScene.user_id == user_id)
            .order_by(CachedScene.cached_at.desc())
        )
        return list(result.scalars().all())

    async def get_cached_scene(self, user_id: int, scene_id: str) -> Optional[CachedScene]:
        result = await self.db.execute(
            select(CachedScene).where(
                CachedScene.user_id == user_id,
                CachedScene.scene_id == scene_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_scene_footprints(self, user_id: int) -> list[dict]:
        scenes = await self.get_cached_scenes(user_id)
        footprints = []
        for scene in scenes:
            if scene.footprint_geojson:
                footprints.append(
                    {
                        "scene_id": scene.scene_id,
                        "collection": scene.collection,
                        "geojson": json.loads(scene.footprint_geojson),
                    }
                )
        return footprints
