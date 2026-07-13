"""Geospatial utility helpers."""

from __future__ import annotations

from typing import Any


def bbox_from_polygon(coordinates: list[list[list[float]]]) -> list[float]:
    """Compute [west, south, east, north] from polygon rings."""
    ring = coordinates[0]
    lons = [c[0] for c in ring]
    lats = [c[1] for c in ring]
    return [min(lons), min(lats), max(lons), max(lats)]


def feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}
