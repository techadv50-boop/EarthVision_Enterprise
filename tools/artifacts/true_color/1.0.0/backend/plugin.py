"""true_color Tool Pack plugin — Natural Color / TCI + highlight-optimized.

Host supplies imagery I/O via HostImageryPort. This module owns tone-mapping
and encode quality defaults for this pack version.
"""

from __future__ import annotations

import base64
from typing import Any

import numpy as np

from app.schemas.composite import CompositeResponse
from app.services.composite_service import COMPOSITE_PRESETS
from app.services.professional_viz import prepare_tci_display, true_color_highlight_optimized
from app.services.satellite_bands import COMPOSITE_REQUIRED_KEYS, composite_for_family, family_label

# Pack-owned knobs (change across pack versions without rebuilding the shell)
PACK_VERSION = "1.0.0"
PNG_QUALITY = 95
STRETCH_TCI = "esa_tci"
STRETCH_BANDS = "highlight_optimized"
MESSAGE_TAG = "tool_pack"


def render(request: Any, host: Any) -> CompositeResponse:
    """Render True Color using host imagery ports."""
    preset_id = "true_color"
    meta = COMPOSITE_PRESETS[preset_id]
    family = host.resolve_family(request.scene_id, request.collection)
    keys = meta["keys"]
    label = meta["label"]
    display = meta["display"]
    sat = composite_for_family(preset_id, family) if family else None
    formula = (sat or {}).get("formula") or meta["formula"]
    band_keys = {"R": keys[0], "G": keys[1], "B": keys[2]}

    size = max(64, min(int(getattr(request, "size", None) or 2048), 2048))
    footprint: dict[str, Any] | None = None

    if request.scene_id:
        visual = host.load_visual_rgb(request.scene_id, request.bbox, size)
        if visual is not None:
            rgb_raw = visual.rgb
            bounds = visual.bounds
            valid_mask = visual.valid_mask
            footprint = visual.footprint
            valid_mask = host.clip_mask_to_footprint(valid_mask, bounds, footprint)
            brightness = float(getattr(request, "brightness", 1.0) or 1.0)
            contrast = float(getattr(request, "contrast", 1.0) or 1.0)
            rgb = prepare_tci_display(
                rgb_raw,
                brightness=brightness if abs(brightness - 1.0) > 0.02 else 1.0,
                contrast=contrast if abs(contrast - 1.0) > 0.02 else 1.0,
            )
            hist = host.rgb_histogram(rgb)
            png = host.rgb_to_png(rgb, valid_mask=valid_mask, quality=PNG_QUALITY)
            return CompositeResponse(
                preset=preset_id,
                label=label,
                bands=display,
                band_keys=band_keys,
                formula=formula,
                bounds=bounds,
                overlay_base64=base64.b64encode(png).decode("ascii"),
                histogram=hist,
                legend=host.rgb_legend(label, formula),
                message=(
                    f"{label} · {family_label(family) if family else 'scene'} · "
                    f"bands {(sat or {}).get('codes', 'RGB')} · {STRETCH_TCI} · "
                    f"preview {size}px · {MESSAGE_TAG}:{PACK_VERSION}"
                ),
                stretch=STRETCH_TCI,
                footprint=footprint,
            )

    bands, bounds, footprint = host.load_bands(
        request.scene_id, request.bbox, size, band_names=COMPOSITE_REQUIRED_KEYS["true_color"]
    )
    r = host.pick_band(bands, keys[0], required=True)
    g = host.pick_band(bands, keys[1], required=True)
    b = host.pick_band(bands, keys[2], required=True)
    valid_mask = np.isfinite(r) & np.isfinite(g) & np.isfinite(b)
    valid_mask = host.clip_mask_to_footprint(valid_mask, bounds, footprint)
    rgb = true_color_highlight_optimized(r, g, b, brightness=1.0, contrast=1.0)
    if valid_mask is not None:
        rgb = rgb.copy()
        rgb[~valid_mask] = 0.0
    hist = host.rgb_histogram(rgb)
    png = host.rgb_to_png(rgb, valid_mask=valid_mask, quality=PNG_QUALITY)
    return CompositeResponse(
        preset=preset_id,
        label=label,
        bands=display,
        band_keys=band_keys,
        formula=formula,
        bounds=bounds,
        overlay_base64=base64.b64encode(png).decode("ascii"),
        histogram=hist,
        legend=host.rgb_legend(label, formula),
        message=(
            f"{label} · {family_label(family) if family else 'scene'} · "
            f"{STRETCH_BANDS} · preview {size}px · {MESSAGE_TAG}:{PACK_VERSION}"
        ),
        stretch=f"{STRETCH_BANDS} p{getattr(request, 'p_low', 2)}-{getattr(request, 'p_high', 98)}",
        footprint=footprint,
    )


def pack_info() -> dict[str, Any]:
    return {
        "tool_id": "true_color",
        "version": PACK_VERSION,
        "png_quality": PNG_QUALITY,
        "message_tag": MESSAGE_TAG,
    }
