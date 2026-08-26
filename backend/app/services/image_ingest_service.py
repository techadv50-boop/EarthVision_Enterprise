"""Multi-format satellite image ingest for SAT EYE offline tools.

Accepts many raster/image formats and normalizes them to a working GeoTIFF
so all 148 GIS tools can operate on the same internal representation.
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

# Extensions accepted for offline upload (case-insensitive)
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # GeoTIFF / COG
        ".tif",
        ".tiff",
        ".geotiff",
        ".cog",
        # JPEG2000
        ".jp2",
        ".j2k",
        ".j2c",
        # Common optical / scanned / derived
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".webp",
        ".gif",
        # Scientific / remote sensing containers
        ".img",  # ERDAS / ENVI
        ".hdr",
        ".nc",
        ".hdf",
        ".h5",
        ".hdf5",
        ".asc",  # ASCII grid
        ".bil",
        ".bsq",
        ".bip",
        ".vrt",
        ".kea",
        ".sid",  # MrSID if GDAL supports
        ".ecw",
    }
)

ACCEPT_ATTRIBUTE = ",".join(sorted(SUPPORTED_EXTENSIONS))


DATE_RE = re.compile(
    r"^(?P<y>20\d{2}|19\d{2})[-/.]?(?P<m>\d{2})[-/.]?(?P<d>\d{2})$"
)
TIME_RE = re.compile(
    r"^(?P<h>\d{1,2}):(?P<min>\d{2})(?::(?P<s>\d{2}))?$"
)


class ImageIngestService:
    """Validate, store, and normalize uploaded imagery for offline GIS tools."""

    @staticmethod
    def supported_formats() -> dict[str, Any]:
        return {
            "extensions": sorted(SUPPORTED_EXTENSIONS),
            "accept": ACCEPT_ATTRIBUTE,
            "notes": (
                "All formats are normalized to a working GeoTIFF so SAT EYE "
                "GIS tools can run against any uploaded image type."
            ),
            "georeferenced_preferred": [
                ".tif",
                ".tiff",
                ".geotiff",
                ".cog",
                ".jp2",
                ".img",
                ".nc",
                ".hdf",
                ".h5",
            ],
            "optical_also_accepted": [
                ".jpg",
                ".jpeg",
                ".png",
                ".bmp",
                ".webp",
                ".gif",
            ],
        }

    @classmethod
    def is_supported(cls, filename: str) -> bool:
        return Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS

    @staticmethod
    def parse_required_date(value: str | None) -> str:
        """Parse acquisition date; raises ValueError if missing/invalid."""
        if not value or not str(value).strip():
            raise ValueError("acquisition_date is required (YYYY-MM-DD)")
        raw = str(value).strip()
        m = DATE_RE.match(raw)
        if not m:
            # Also accept ISO datetime prefix
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return dt.date().isoformat()
            except ValueError as exc:
                raise ValueError(
                    "acquisition_date must be YYYY-MM-DD (e.g. 2024-06-15)"
                ) from exc
        y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
        try:
            return datetime(y, mo, d).date().isoformat()
        except ValueError as exc:
            raise ValueError("acquisition_date is not a valid calendar date") from exc

    @staticmethod
    def parse_optional_time(value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        raw = str(value).strip()
        m = TIME_RE.match(raw)
        if not m:
            raise ValueError("acquisition_time must be HH:MM or HH:MM:SS")
        h = int(m.group("h"))
        mi = int(m.group("min"))
        s = int(m.group("s") or 0)
        if not (0 <= h <= 23 and 0 <= mi <= 59 and 0 <= s <= 59):
            raise ValueError("acquisition_time out of range")
        return f"{h:02d}:{mi:02d}:{s:02d}"

    def ingest(
        self,
        source_path: Path,
        dest_dir: Path,
        *,
        original_filename: str | None = None,
    ) -> dict[str, Any]:
        """Copy/normalize an uploaded file into dest_dir.

        Returns paths + raster info. ``working_path`` is always a GeoTIFF
        suitable for tiling and the 148 GIS tools.
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        name = original_filename or source_path.name
        if not self.is_supported(name):
            raise ValueError(
                f"Unsupported format '{Path(name).suffix}'. "
                f"Accepted: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        safe = Path(name).name
        original_path = dest_dir / safe
        if source_path.resolve() != original_path.resolve():
            shutil.copy2(source_path, original_path)

        working_path, convert_note = self.normalize_to_geotiff(original_path, dest_dir)
        info = self._safe_tile_info(working_path)
        center = self._center_from_info(info)

        return {
            "original_path": str(original_path),
            "working_path": str(working_path),
            "original_format": Path(name).suffix.lower(),
            "normalized": working_path.resolve() != original_path.resolve(),
            "convert_note": convert_note,
            "info": info,
            "longitude": center[0] if center else None,
            "latitude": center[1] if center else None,
        }

    def normalize_to_geotiff(self, path: Path, dest_dir: Path) -> tuple[Path, str]:
        """Ensure a GeoTIFF working copy exists for tool execution."""
        suffix = path.suffix.lower()
        # Already GeoTIFF-like — try open as-is first
        if suffix in {".tif", ".tiff", ".geotiff", ".cog"}:
            if self._can_open_rasterio(path):
                return path, "native_geotiff"
            # Fall through to Pillow rewrite if corrupt / unusual

        out = dest_dir / f"{path.stem}.working.tif"
        if out.exists() and out.stat().st_mtime >= path.stat().st_mtime:
            return out, "cached_working_geotiff"

        # Prefer GDAL/rasterio translate for RS formats
        if self._can_open_rasterio(path):
            self._rasterio_to_geotiff(path, out)
            return out, f"rasterio_translate_from_{suffix}"

        # Optical images via Pillow → single/multi-band GeoTIFF (local CRS)
        if suffix in {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}:
            self._pillow_to_geotiff(path, out)
            return out, f"pillow_georef_placeholder_from_{suffix}"

        raise ValueError(
            f"Could not open '{path.name}' as a raster. "
            "Install GDAL drivers for this format, or convert to GeoTIFF/PNG/JPEG."
        )

    def ensure_working_path(self, file_path: str) -> str:
        """Return a GeoTIFF path tools can open (normalize on demand)."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {file_path}")
        if path.suffix.lower() in {".tif", ".tiff", ".geotiff", ".cog"} and self._can_open_rasterio(path):
            return str(path)
        working, _ = self.normalize_to_geotiff(path, path.parent)
        return str(working)

    @staticmethod
    def _can_open_rasterio(path: Path) -> bool:
        try:
            import rasterio

            with rasterio.open(path) as src:
                return src.width > 0 and src.height > 0
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _rasterio_to_geotiff(src_path: Path, dst_path: Path) -> None:
        import rasterio

        with rasterio.open(src_path) as src:
            profile = src.profile.copy()
            profile.update(
                driver="GTiff",
                compress="lzw",
                tiled=True,
                blockxsize=256,
                blockysize=256,
            )
            # Some formats omit CRS — keep as-is; tools still run
            data = src.read()
            with rasterio.open(dst_path, "w", **profile) as dst:
                dst.write(data)

    @staticmethod
    def _pillow_to_geotiff(src_path: Path, dst_path: Path) -> None:
        """Write a non-georeferenced optical image as GeoTIFF with identity geotransform."""
        import rasterio
        from PIL import Image
        from rasterio.transform import from_origin

        img = Image.open(src_path)
        img = img.convert("RGB") if img.mode not in ("L", "RGB", "RGBA") else img
        arr = np.array(img)
        if arr.ndim == 2:
            bands = arr[np.newaxis, ...]
        elif arr.shape[2] == 4:
            bands = np.transpose(arr[:, :, :3], (2, 0, 1))
        else:
            bands = np.transpose(arr, (2, 0, 1))

        height, width = bands.shape[1], bands.shape[2]
        # Placeholder georef so GIS tools have a CRS/transform (1px ≈ 1m local)
        transform = from_origin(0.0, float(height), 1.0, 1.0)
        profile = {
            "driver": "GTiff",
            "height": height,
            "width": width,
            "count": bands.shape[0],
            "dtype": bands.dtype.name,
            "crs": "EPSG:3857",
            "transform": transform,
            "compress": "lzw",
        }
        with rasterio.open(dst_path, "w", **profile) as dst:
            dst.write(bands)
            dst.update_tags(
                SAT_EYE_NOTE="Optical image normalized without native georeferencing"
            )

    @staticmethod
    def _safe_tile_info(path: Path) -> dict[str, Any] | None:
        try:
            from app.services.raster_service import RasterService

            return RasterService().get_tile_info(str(path))
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _center_from_info(info: dict[str, Any] | None) -> tuple[float, float] | None:
        if not info or "bounds" not in info:
            return None
        b = info["bounds"]
        try:
            if isinstance(b, (list, tuple)) and len(b) >= 4:
                return (float(b[0]) + float(b[2])) / 2, (float(b[1]) + float(b[3])) / 2
            if isinstance(b, dict):
                return (
                    (float(b["left"]) + float(b["right"])) / 2,
                    (float(b["bottom"]) + float(b["top"])) / 2,
                )
        except Exception:  # noqa: BLE001
            return None
        return None
