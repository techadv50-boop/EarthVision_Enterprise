"""Multi-date imagery stacks for the same place — powers the SAT EYE date slider."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings


class ImageryStackService:
    """Group uploaded satellite images by place for temporal browsing."""

    def __init__(self) -> None:
        settings = get_settings()
        self.root = settings.offline_data_dir / "stacks"
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "stacks_index.json"
        if not self.index_path.exists():
            self._write_index({"stacks": {}})

    def _read_index(self) -> dict[str, Any]:
        return json.loads(self.index_path.read_text())

    def _write_index(self, data: dict[str, Any]) -> None:
        self.index_path.write_text(json.dumps(data, indent=2))

    def list_stacks(self) -> list[dict[str, Any]]:
        data = self._read_index()
        stacks = []
        for sid, stack in data.get("stacks", {}).items():
            stacks.append(self._public_stack(sid, stack))
        stacks.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
        return stacks

    def get_stack(self, stack_id: str) -> dict[str, Any] | None:
        data = self._read_index()
        stack = data.get("stacks", {}).get(stack_id)
        if not stack:
            return None
        return self._public_stack(stack_id, stack)

    def create_stack(
        self,
        name: str,
        place_key: str | None = None,
        longitude: float | None = None,
        latitude: float | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        data = self._read_index()
        stack_id = str(uuid.uuid4())[:12]
        now = datetime.now(timezone.utc).isoformat()
        stack = {
            "name": name,
            "place_key": place_key or name.lower().replace(" ", "_"),
            "longitude": longitude,
            "latitude": latitude,
            "description": description,
            "created_at": now,
            "updated_at": now,
            "images": [],
        }
        data["stacks"][stack_id] = stack
        self._write_index(data)
        return self._public_stack(stack_id, stack)

    def add_image(
        self,
        stack_id: str,
        *,
        file_path: str,
        acquisition_date: str,
        label: str | None = None,
        cloud_cover: float | None = None,
        metadata: dict[str, Any] | None = None,
        footprint_geojson: str | None = None,
        working_path: str | None = None,
        acquisition_time: str | None = None,
        original_format: str | None = None,
    ) -> dict[str, Any] | None:
        from app.services.image_ingest_service import ImageIngestService

        data = self._read_index()
        stack = data.get("stacks", {}).get(stack_id)
        if not stack:
            return None

        date = ImageIngestService.parse_required_date(acquisition_date)
        time_val = ImageIngestService.parse_optional_time(acquisition_time)

        work = working_path or file_path
        # Try to enrich from raster bounds if lon/lat missing
        if stack.get("longitude") is None or stack.get("latitude") is None:
            center = self._raster_center(work)
            if center:
                stack["longitude"], stack["latitude"] = center

        image_id = str(uuid.uuid4())[:10]
        meta = dict(metadata or {})
        if time_val:
            meta["acquisition_time"] = time_val
        if original_format:
            meta["original_format"] = original_format
        meta.setdefault("working_path", work)

        image = {
            "id": image_id,
            "file_path": file_path,
            "working_path": work,
            "acquisition_date": date,
            "acquisition_time": time_val,
            "label": label or Path(file_path).name,
            "cloud_cover": cloud_cover,
            "metadata": meta,
            "footprint_geojson": footprint_geojson,
            "original_format": original_format or Path(file_path).suffix.lower(),
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        stack["images"].append(image)
        # Sort by date then time so slider order is chronological
        stack["images"].sort(
            key=lambda im: (
                im.get("acquisition_date") or "",
                im.get("acquisition_time") or "",
            )
        )
        stack["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_index(data)
        return self._public_stack(stack_id, stack)

    def find_or_create_for_place(
        self,
        place_name: str,
        longitude: float | None = None,
        latitude: float | None = None,
        tolerance_deg: float = 0.25,
    ) -> dict[str, Any]:
        """Find an existing stack near the same place, or create one."""
        data = self._read_index()
        place_key = place_name.lower().strip().replace(" ", "_")
        for sid, stack in data.get("stacks", {}).items():
            if stack.get("place_key") == place_key:
                return self._public_stack(sid, stack)
            if (
                longitude is not None
                and latitude is not None
                and stack.get("longitude") is not None
                and stack.get("latitude") is not None
            ):
                if (
                    abs(stack["longitude"] - longitude) <= tolerance_deg
                    and abs(stack["latitude"] - latitude) <= tolerance_deg
                ):
                    return self._public_stack(sid, stack)
        return self.create_stack(place_name, place_key=place_key, longitude=longitude, latitude=latitude)

    def seed_demo_stack(self) -> dict[str, Any]:
        """Create a 20-image demo stack for the date slider (placeholder paths)."""
        existing = self.list_stacks()
        for s in existing:
            if s.get("place_key") == "demo_valley" and s.get("image_count", 0) >= 20:
                return s

        stack = self.create_stack(
            name="Demo Valley Time Series",
            place_key="demo_valley",
            longitude=0.0,
            latitude=0.0,
            description="20-date demo stack for SAT EYE temporal slider (offline)",
        )
        stack_id = stack["id"]
        # Re-open and inject 20 dated entries
        data = self._read_index()
        images = []
        for i in range(20):
            month = (i % 12) + 1
            year = 2024 + (i // 12)
            date = f"{year}-{month:02d}-15"
            images.append(
                {
                    "id": f"demo{i:02d}",
                    "file_path": f"demo://demo_valley/{date}.tif",
                    "acquisition_date": date,
                    "label": f"Demo {date}",
                    "cloud_cover": float((i * 7) % 40),
                    "metadata": {"sensor": "Sentinel-2", "demo": True},
                    "footprint_geojson": json.dumps(
                        {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [-1.5, -1.5],
                                    [1.5, -1.5],
                                    [1.5, 1.5],
                                    [-1.5, 1.5],
                                    [-1.5, -1.5],
                                ]
                            ],
                        }
                    ),
                    "added_at": datetime.now(timezone.utc).isoformat(),
                    "is_demo": True,
                }
            )
        data["stacks"][stack_id]["images"] = images
        data["stacks"][stack_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_index(data)
        return self.get_stack(stack_id)  # type: ignore[return-value]

    def _public_stack(self, stack_id: str, stack: dict[str, Any]) -> dict[str, Any]:
        images = stack.get("images") or []
        dates = [im.get("acquisition_date") for im in images if im.get("acquisition_date")]
        # Unique acquisition dates (slider steps = one entry per uploaded image)
        unique_dates = sorted({d for d in dates if d})
        return {
            "id": stack_id,
            "name": stack.get("name"),
            "place_key": stack.get("place_key"),
            "longitude": stack.get("longitude"),
            "latitude": stack.get("latitude"),
            "description": stack.get("description"),
            "created_at": stack.get("created_at"),
            "updated_at": stack.get("updated_at"),
            "image_count": len(images),
            "slider_max_index": max(0, len(images) - 1),
            "date_count": len(unique_dates),
            "date_min": min(dates) if dates else None,
            "date_max": max(dates) if dates else None,
            "has_slider": len(images) >= 2,
            "images": images,
        }

    @staticmethod
    def _infer_date(file_path: str) -> str | None:
        name = Path(file_path).stem
        # Try YYYYMMDD or YYYY-MM-DD in filename
        import re

        m = re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", name)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        return None

    @staticmethod
    def _raster_center(file_path: str) -> tuple[float, float] | None:
        path = Path(file_path)
        if not path.exists() or path.stat().st_size == 0:
            return None
        try:
            import rasterio

            with rasterio.open(path) as src:
                b = src.bounds
                return ((b.left + b.right) / 2.0, (b.bottom + b.top) / 2.0)
        except Exception:  # noqa: BLE001
            return None
