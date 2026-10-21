"""Host SDK ports for Tool Packs — stable imagery / encode façade.

Packs must not import FastAPI routers or Workspace internals. They receive a
HostImageryPort implemented by the shell.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np


@dataclass
class VisualRgbLoad:
    rgb: np.ndarray
    bounds: list[float]
    valid_mask: np.ndarray
    footprint: dict[str, Any] | None


class HostImageryPort(Protocol):
    def load_visual_rgb(
        self, scene_id: str, bbox: list[float] | None, size: int
    ) -> VisualRgbLoad | None: ...

    def load_bands(
        self,
        scene_id: str | None,
        bbox: list[float] | None,
        size: int,
        band_names: tuple[str, ...] | list[str],
    ) -> tuple[dict[str, np.ndarray], list[float], dict[str, Any] | None]: ...

    def pick_band(
        self, bands: dict[str, np.ndarray], key: str, *, required: bool = False
    ) -> np.ndarray: ...

    def clip_mask_to_footprint(
        self,
        valid_mask: np.ndarray,
        bounds: list[float],
        footprint: dict[str, Any] | None,
    ) -> np.ndarray: ...

    def rgb_to_png(
        self,
        rgb: np.ndarray,
        valid_mask: np.ndarray | None = None,
        *,
        quality: int = 95,
    ) -> bytes: ...

    def rgb_histogram(self, rgb: np.ndarray) -> dict[str, Any]: ...

    def rgb_legend(self, label: str, formula: str) -> Any: ...

    def resolve_family(self, scene_id: str | None, collection: str | None) -> str | None: ...


def composite_host_port() -> HostImageryPort:
    """Adapter over CompositeService helpers (shell implementation)."""
    from app.services.composite_service import CompositeService

    svc = CompositeService()

    class _Port:
        def load_visual_rgb(self, scene_id: str, bbox: list[float] | None, size: int):
            visual = svc._load_visual_rgb(scene_id, bbox, size)
            if visual is None:
                return None
            rgb, bounds, valid_mask, footprint = visual
            return VisualRgbLoad(rgb, bounds, valid_mask, footprint)

        def load_bands(self, scene_id, bbox, size, band_names):
            return svc._load_bands(scene_id, bbox, size, band_names=band_names)

        def pick_band(self, bands, key, *, required=False):
            return svc._pick(bands, key, required=required)

        def clip_mask_to_footprint(self, valid_mask, bounds, footprint):
            return svc._clip_mask_to_footprint(valid_mask, bounds, footprint)

        def rgb_to_png(self, rgb, valid_mask=None, *, quality=95):
            return svc._rgb_to_png(rgb, valid_mask=valid_mask, quality=quality)

        def rgb_histogram(self, rgb):
            return svc._rgb_histogram(rgb)

        def rgb_legend(self, label, formula):
            return svc._rgb_legend(label, formula)

        def resolve_family(self, scene_id, collection):
            return svc._resolve_family(scene_id, collection)

    return _Port()
