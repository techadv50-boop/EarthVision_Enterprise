"""Plugin permission *declarations* — NOT a sandbox.

These tokens are an allowlist of declared capabilities checked at validate/install
time. They do **not** isolate process memory, filesystem, network, or database
access. Uploaded plugin Python is not executed in the FastAPI process;
see docs/PLUGIN_TRUST_BOUNDARY.md.
"""

from __future__ import annotations

# Explicitly allowed capability tokens (declarative only).
ALLOWED_PERMISSIONS = frozenset(
    {
        "synthetic_data",
        "ui.slot.left_toolbar",
        "ui.slot.right_analysis_panel",
        "ui.slot.map_overlay",
        "ui.slot.results_panel",
        "host.sdk.read_meta",
        # P2B/RC GIS Host SDK (no Leaflet / no auth tokens)
        "host.sdk.read_aoi",
        "host.sdk.set_analysis_result",
        "host.sdk.read_analysis_result",
        # Optical true-color imagery (Host Shell side-effects; no Leaflet in iframe)
        "host.sdk.read_scene",
        "host.sdk.read_capabilities",
        "host.sdk.render_true_color",
        "host.sdk.clear_map_layer",
        "host.sdk.export_geotiff",
        "host.sdk.export_map_jpeg",
    }
)

# Hard rejects — never grant these.
FORBIDDEN_PERMISSIONS = frozenset(
    {
        "filesystem",
        "filesystem.write",
        "filesystem.read",
        "network",
        "network.egress",
        "database",
        "database.write",
        "database.read",
        "shell",
        "subprocess",
        "admin",
        "arbitrary_code",
        "leaflet",
        "auth.token",
    }
)


def validate_permissions(requested: list[str] | None) -> list[str]:
    perms = [str(p).strip() for p in (requested or []) if str(p).strip()]
    bad = [p for p in perms if p in FORBIDDEN_PERMISSIONS or p not in ALLOWED_PERMISSIONS]
    if bad:
        raise ValueError(f"invalid or forbidden permissions: {bad}")
    return perms
