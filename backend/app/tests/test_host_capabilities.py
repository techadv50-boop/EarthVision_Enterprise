"""Frozen Host geospatial capability profile tests."""

from __future__ import annotations

from app.host_capabilities import (
    HOST_CAPABILITIES,
    HOST_GEO_PROFILE_ID,
    HOST_TOOL_FAMILIES,
    assert_capabilities,
    host_capabilities_document,
)


def test_profile_id_stable():
    assert HOST_GEO_PROFILE_ID == "sateye-rs-2026.10"


def test_capabilities_append_only_core_keys():
    # Renaming these would break plugin contracts — keep forever.
    required = {
        "host.math.numpy",
        "host.raster.rasterio",
        "host.vector.shapely",
        "host.map.prefer_scene_tiles",
        "host.map.processed_preview",
        "host.map.vector_geojson",
        "host.analytics.composites",
        "host.analytics.indices",
    }
    assert required.issubset(HOST_CAPABILITIES.keys())


def test_tool_families_reference_known_caps():
    for family, caps in HOST_TOOL_FAMILIES.items():
        assert caps, family
        for cid in caps:
            assert cid in HOST_CAPABILITIES, f"{family} -> {cid}"


def test_capabilities_document_shape():
    doc = host_capabilities_document()
    assert doc["profile_id"] == HOST_GEO_PROFILE_ID
    assert doc["approach"] == "host_shared_stack"
    assert "prefer_scene_tiles" in doc["map_presentation_modes"]
    assert isinstance(doc["capabilities"], dict)
    assert isinstance(doc["ready"], list)


def test_assert_capabilities_unknown():
    missing = assert_capabilities(["host.math.numpy", "host.does.not.exist"])
    assert "host.does.not.exist" in missing
