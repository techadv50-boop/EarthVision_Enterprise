"""Fast overlay encoding tuned for slow networks (small wire size)."""

from __future__ import annotations

import io
from typing import Literal

import numpy as np
from PIL import Image

OverlayFormat = Literal["webp", "png", "jpeg"]


def encode_rgba_overlay(
    rgba: np.ndarray,
    *,
    prefer: OverlayFormat = "webp",
    quality: int = 72,
) -> tuple[bytes, str]:
    """Encode RGBA uint8 overlay → (bytes, mime). Prefer WebP for size+alpha."""
    if rgba.ndim != 3 or rgba.shape[2] not in (3, 4):
        raise ValueError("rgba must be HxWx3 or HxWx4")
    if rgba.shape[2] == 3:
        alpha = np.full(rgba.shape[:2], 255, dtype=np.uint8)
        rgba = np.dstack([rgba, alpha])
    img = Image.fromarray(rgba.astype(np.uint8, copy=False), mode="RGBA")
    buf = io.BytesIO()
    if prefer == "webp":
        try:
            # method=0 → fastest encode; quality trades size vs fidelity
            img.save(buf, format="WEBP", quality=int(quality), method=0)
            return buf.getvalue(), "image/webp"
        except Exception:  # noqa: BLE001
            buf = io.BytesIO()
    if prefer == "jpeg":
        # Flatten transparent pixels to black for RGB JPEG
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img, mask=img.split()[-1])
        bg.save(buf, format="JPEG", quality=int(quality), optimize=False)
        return buf.getvalue(), "image/jpeg"
    # PNG: higher compress_level → smaller download on slow links
    img.save(buf, format="PNG", optimize=False, compress_level=6)
    return buf.getvalue(), "image/png"


def encode_categorical_overlay(rgba: np.ndarray) -> tuple[bytes, str]:
    """Lossless WebP (fallback PNG) for flat class colors — no smear."""
    if rgba.ndim != 3 or rgba.shape[2] not in (3, 4):
        raise ValueError("rgba must be HxWx3 or HxWx4")
    if rgba.shape[2] == 3:
        alpha = np.full(rgba.shape[:2], 255, dtype=np.uint8)
        rgba = np.dstack([rgba, alpha])
    img = Image.fromarray(rgba.astype(np.uint8, copy=False), mode="RGBA")
    buf = io.BytesIO()
    try:
        img.save(buf, format="WEBP", lossless=True, method=0)
        return buf.getvalue(), "image/webp"
    except Exception:  # noqa: BLE001
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False, compress_level=6)
        return buf.getvalue(), "image/png"


def encode_rgb_mask_overlay(
    rgb: np.ndarray,
    valid_mask: np.ndarray | None = None,
    *,
    quality: int = 72,
) -> tuple[bytes, str]:
    """RGB float/uint8 + mask → compact WebP/PNG overlay."""
    if rgb.dtype != np.uint8:
        u8 = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    else:
        u8 = rgb
    if valid_mask is None:
        valid_mask = np.any(u8 > 2, axis=2)
    alpha = np.where(valid_mask, 255, 0).astype(np.uint8)
    rgba = np.dstack([u8, alpha])
    return encode_rgba_overlay(rgba, prefer="webp", quality=quality)
