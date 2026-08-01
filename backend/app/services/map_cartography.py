"""Cartographic decorations for map-sheet GeoTIFF / PNG exports.

Adds north arrow, scale bar, left+bottom coordinate ticks/grid, and a legend
(with area in km²) around a georeferenced classification overlay.
"""

from __future__ import annotations

import io
import math
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def _hex_rgb(hex_color: str) -> tuple[int, int, int]:
    h = (hex_color or "#888888").lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6:
        return (128, 128, 128)
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return (128, 128, 128)


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _nice_scale_m(map_width_m: float) -> float:
    """Pick a round scale-bar length (~1/4 of map width)."""
    target = max(map_width_m / 4.0, 100.0)
    exp = math.floor(math.log10(target))
    base = 10**exp
    for mult in (1, 2, 5, 10, 20, 50):
        if mult * base >= target * 0.55:
            return float(mult * base)
    return float(10 * base)


def _format_scale_label(meters: float) -> str:
    if meters >= 1000:
        km = meters / 1000.0
        return f"{km:g} km"
    return f"{int(round(meters))} m"


def _format_coord(value: float, is_lon: bool) -> str:
    hemi = ("E" if value >= 0 else "W") if is_lon else ("N" if value >= 0 else "S")
    return f"{abs(value):.3f}°{hemi}"


def _grid_step(span: float) -> float:
    """Nice tick step for a geographic span in degrees."""
    if span <= 0:
        return 0.01
    raw = span / 5.0
    exp = math.floor(math.log10(raw))
    base = 10**exp
    for mult in (1, 2, 5, 10):
        if mult * base >= raw * 0.7:
            return float(mult * base)
    return float(10 * base)


def decorate_classification_map(
    png_bytes: bytes,
    bounds: list[float],
    legend_items: list[dict[str, Any]],
    *,
    title: str = "Land Cover Classification",
    total_area_km2: float | None = None,
) -> tuple[bytes, list[float]]:
    """Compose a map sheet with cartography; return PNG + extended geo bounds.

    Layout:
      [ map | legend ]
      [ bottom collar: lon ticks ]

    Grid ticks/labels only on the **left** and **bottom** of the map frame.
    Legend includes each class area in km².
    """
    if not png_bytes:
        raise ValueError("No image to decorate")
    if not bounds or len(bounds) != 4:
        raise ValueError("bounds [west,south,east,north] required")

    west, south, east, north = (float(v) for v in bounds)
    if east <= west or north <= south:
        raise ValueError("Invalid bounds")

    map_img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    map_w, map_h = map_img.size

    # Layout metrics (scale with map size)
    pad = max(12, min(map_w, map_h) // 40)
    legend_w = max(220, min(340, map_w // 3))
    bottom_h = max(72, min(120, map_h // 10))
    tick_len = max(6, pad // 2)
    title_h = max(28, pad + 16)

    # Extra left margin so lat labels don't clip
    left_margin = max(pad, 56)
    canvas_w = left_margin + map_w + legend_w + pad * 2
    canvas_h = title_h + map_h + bottom_h + pad * 2
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    font_sm = _font(max(10, min(14, map_w // 90)))
    font_md = _font(max(12, min(16, map_w // 70)))
    font_lg = _font(max(14, min(20, map_w // 55)))

    map_x0 = left_margin
    map_y0 = title_h + pad // 2
    map_x1 = map_x0 + map_w
    map_y1 = map_y0 + map_h

    # Title
    draw.text((left_margin, 8), title, fill=(15, 23, 42, 255), font=font_lg)

    # Paste classification map
    canvas.paste(map_img, (map_x0, map_y0), map_img)

    # Map frame
    draw.rectangle(
        [map_x0 - 1, map_y0 - 1, map_x1, map_y1],
        outline=(30, 41, 59, 255),
        width=2,
    )

    # ---- Left + bottom coordinate grid (ticks only on those sides) ----
    lon_span = east - west
    lat_span = north - south
    lon_step = _grid_step(lon_span)
    lat_step = _grid_step(lat_span)

    def lon_to_x(lon: float) -> int:
        return int(round(map_x0 + (lon - west) / lon_span * map_w))

    def lat_to_y(lat: float) -> int:
        return int(round(map_y0 + (north - lat) / lat_span * map_h))

    # Bottom lon ticks + short inward grid stubs
    lon0 = math.ceil(west / lon_step) * lon_step
    lon = lon0
    while lon <= east + 1e-12:
        x = lon_to_x(lon)
        if map_x0 <= x <= map_x1:
            draw.line([(x, map_y1), (x, map_y1 + tick_len)], fill=(51, 65, 85, 255), width=1)
            draw.line(
                [(x, map_y1), (x, max(map_y0, map_y1 - tick_len * 3))],
                fill=(100, 116, 139, 160),
                width=1,
            )
            label = _format_coord(lon, True)
            bbox = draw.textbbox((0, 0), label, font=font_sm)
            tw = bbox[2] - bbox[0]
            draw.text(
                (x - tw // 2, map_y1 + tick_len + 2),
                label,
                fill=(51, 65, 85, 255),
                font=font_sm,
            )
        lon += lon_step

    # Left lat ticks + short inward grid stubs
    lat0 = math.ceil(south / lat_step) * lat_step
    lat = lat0
    while lat <= north + 1e-12:
        y = lat_to_y(lat)
        if map_y0 <= y <= map_y1:
            draw.line([(map_x0 - tick_len, y), (map_x0, y)], fill=(51, 65, 85, 255), width=1)
            draw.line(
                [(map_x0, y), (min(map_x1, map_x0 + tick_len * 3), y)],
                fill=(100, 116, 139, 160),
                width=1,
            )
            label = _format_coord(lat, False)
            bbox = draw.textbbox((0, 0), label, font=font_sm)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.text(
                (max(2, map_x0 - tick_len - tw - 4), y - th // 2),
                label,
                fill=(51, 65, 85, 255),
                font=font_sm,
            )
        lat += lat_step

    # ---- North arrow (top-right of map) ----
    na_x = map_x1 - pad * 2 - 10
    na_y = map_y0 + pad + 8
    draw.line([(na_x, na_y + 28), (na_x, na_y + 6)], fill=(15, 23, 42, 255), width=3)
    draw.polygon(
        [(na_x, na_y), (na_x - 8, na_y + 14), (na_x + 8, na_y + 14)],
        fill=(15, 23, 42, 255),
    )
    draw.text((na_x - 5, na_y + 30), "N", fill=(15, 23, 42, 255), font=font_md)

    # ---- Scale bar (bottom-left of map) ----
    mid_lat = (south + north) / 2.0
    m_per_deg_lon = 111_320.0 * max(0.2, math.cos(math.radians(mid_lat)))
    map_width_m = lon_span * m_per_deg_lon
    scale_m = _nice_scale_m(map_width_m)
    scale_px = max(40, int(round((scale_m / map_width_m) * map_w)))
    sb_x = map_x0 + pad
    sb_y = map_y1 - pad - 28
    draw.rectangle(
        [sb_x - 6, sb_y - 18, sb_x + scale_px + 8, sb_y + 16],
        fill=(255, 255, 255, 210),
        outline=(30, 41, 59, 255),
    )
    segs = 4
    seg_w = scale_px / segs
    for i in range(segs):
        x0 = sb_x + int(i * seg_w)
        x1 = sb_x + int((i + 1) * seg_w)
        fill = (15, 23, 42, 255) if i % 2 == 0 else (248, 250, 252, 255)
        draw.rectangle([x0, sb_y, x1, sb_y + 8], fill=fill, outline=(15, 23, 42, 255))
    draw.text(
        (sb_x, sb_y - 16),
        f"Scale  {_format_scale_label(scale_m)}",
        fill=(15, 23, 42, 255),
        font=font_sm,
    )

    # ---- Legend panel (right) with area km² ----
    lx0 = map_x1 + pad
    ly0 = map_y0
    lx1 = canvas_w - pad
    ly1 = map_y1
    draw.rectangle(
        [lx0, ly0, lx1, ly1],
        fill=(248, 250, 252, 255),
        outline=(30, 41, 59, 255),
        width=2,
    )
    draw.text((lx0 + 10, ly0 + 8), "Legend", fill=(15, 23, 42, 255), font=font_md)
    draw.text(
        (lx0 + 10, ly0 + 28),
        "Class / Area (km²)",
        fill=(71, 85, 105, 255),
        font=font_sm,
    )

    items = legend_items or []
    row_y = ly0 + 50
    row_h = max(22, min(32, (ly1 - ly0 - 90) // max(len(items), 1)))
    for item in items:
        if row_y + row_h > ly1 - 40:
            break
        color = _hex_rgb(str(item.get("color") or "#888888"))
        label = str(item.get("label") or item.get("name") or "Class")
        area = item.get("area_km2")
        try:
            area_txt = f"{float(area):.3f}" if area is not None else "—"
        except (TypeError, ValueError):
            area_txt = "—"
        draw.rectangle(
            [lx0 + 10, row_y, lx0 + 28, row_y + 14],
            fill=(*color, 255),
            outline=(15, 23, 42, 255),
        )
        draw.text(
            (lx0 + 34, row_y - 1),
            label[:22],
            fill=(15, 23, 42, 255),
            font=font_sm,
        )
        draw.text(
            (lx0 + 34, row_y + 12),
            f"{area_txt} km²",
            fill=(71, 85, 105, 255),
            font=font_sm,
        )
        row_y += row_h

    if total_area_km2 is not None:
        draw.line([(lx0 + 8, ly1 - 32), (lx1 - 8, ly1 - 32)], fill=(148, 163, 184, 255))
        draw.text(
            (lx0 + 10, ly1 - 26),
            f"Total  {float(total_area_km2):.3f} km²",
            fill=(15, 23, 42, 255),
            font=font_sm,
        )

    draw.text(
        (left_margin, canvas_h - 18),
        "EarthVision Enterprise  ·  EPSG:4326  ·  Grid: left & bottom",
        fill=(100, 116, 139, 255),
        font=font_sm,
    )

    # Extended geographic bounds so the map pixels keep correct geotransform
    px_w = lon_span / map_w
    px_h = lat_span / map_h
    ext_west = west - map_x0 * px_w
    ext_north = north + map_y0 * px_h
    ext_east = ext_west + canvas_w * px_w
    ext_south = ext_north - canvas_h * px_h

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", compress_level=6)
    return buf.getvalue(), [ext_west, ext_south, ext_east, ext_north]
