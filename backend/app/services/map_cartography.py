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
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
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


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _paste_vertical_label(
    canvas: Image.Image,
    text: str,
    *,
    cx: int,
    cy: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int] = (15, 23, 42, 255),
) -> None:
    """Draw text rotated 90° CCW (reads upward) centered at (cx, cy)."""
    # Render horizontally first, then rotate
    tmp = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp)
    tw, th = _text_size(tmp_draw, text, font)
    pad = 4
    label_img = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(label_img).text((pad, pad), text, fill=fill, font=font)
    rotated = label_img.rotate(90, expand=True)
    rw, rh = rotated.size
    canvas.paste(rotated, (int(cx - rw / 2), int(cy - rh / 2)), rotated)


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
      centered title
      [ vertical lat labels | map | legend ]
      [ bottom collar: lon ticks + scale ]

    Grid ticks/labels only on the **left** and **bottom** of the map frame.
    Legend includes each class area in km².
    Elements are sized to remain readable when the GeoTIFF is viewed at 100%.
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
    short = min(map_w, map_h)

    # ---- Readable sizes at 100% zoom (scale with map, with solid floors) ----
    font_grid = _font(max(28, short // 36))
    font_legend = _font(max(26, short // 38))
    font_legend_title = _font(max(32, short // 30))
    font_scale = _font(max(26, short // 38))
    font_north = _font(max(36, short // 28))
    font_title = _font(max(40, short // 24))
    font_footer = _font(max(18, short // 55))

    pad = max(24, short // 28)
    tick_len = max(12, short // 70)
    title_h = max(64, int(font_title.size * 1.8) if hasattr(font_title, "size") else 72)
    bottom_h = max(90, short // 12)

    # Probe a typical lat label to size the left collar for vertical text
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    sample_lat = _format_coord((south + north) / 2.0, False)
    sample_tw, sample_th = _text_size(probe, sample_lat, font_grid)
    # After 90° rotate, text width becomes vertical extent; text height becomes collar width
    left_margin = max(pad + tick_len + sample_th + 28, 90)

    items = legend_items or []
    # Wide legend so labels + area stay readable
    legend_w = max(320, min(480, max(short // 3, 280 + len(items) * 4)))

    canvas_w = left_margin + map_w + legend_w + pad * 2
    canvas_h = title_h + map_h + bottom_h + pad * 2
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    map_x0 = left_margin
    map_y0 = title_h
    map_x1 = map_x0 + map_w
    map_y1 = map_y0 + map_h

    # ---- Centered title ----
    tw, th = _text_size(draw, title, font_title)
    draw.text(
        ((canvas_w - tw) // 2, max(10, (title_h - th) // 2)),
        title,
        fill=(15, 23, 42, 255),
        font=font_title,
    )

    # Paste classification map
    canvas.paste(map_img, (map_x0, map_y0), map_img)

    # Map frame (thicker for visibility)
    draw.rectangle(
        [map_x0 - 2, map_y0 - 2, map_x1 + 1, map_y1 + 1],
        outline=(30, 41, 59, 255),
        width=3,
    )

    # ---- Left + bottom coordinate grid ----
    lon_span = east - west
    lat_span = north - south
    lon_step = _grid_step(lon_span)
    lat_step = _grid_step(lat_span)

    def lon_to_x(lon: float) -> int:
        return int(round(map_x0 + (lon - west) / lon_span * map_w))

    def lat_to_y(lat: float) -> int:
        return int(round(map_y0 + (north - lat) / lat_span * map_h))

    # Bottom lon ticks + labels (horizontal)
    lon0 = math.ceil(west / lon_step) * lon_step
    lon = lon0
    while lon <= east + 1e-12:
        x = lon_to_x(lon)
        if map_x0 <= x <= map_x1:
            draw.line(
                [(x, map_y1), (x, map_y1 + tick_len)],
                fill=(51, 65, 85, 255),
                width=3,
            )
            draw.line(
                [(x, map_y1), (x, max(map_y0, map_y1 - tick_len * 4))],
                fill=(100, 116, 139, 180),
                width=2,
            )
            label = _format_coord(lon, True)
            ltw, _ = _text_size(draw, label, font_grid)
            draw.text(
                (x - ltw // 2, map_y1 + tick_len + 8),
                label,
                fill=(15, 23, 42, 255),
                font=font_grid,
            )
        lon += lon_step

    # Left lat ticks + vertical labels (read upward)
    lat0 = math.ceil(south / lat_step) * lat_step
    lat = lat0
    while lat <= north + 1e-12:
        y = lat_to_y(lat)
        if map_y0 <= y <= map_y1:
            draw.line(
                [(map_x0 - tick_len, y), (map_x0, y)],
                fill=(51, 65, 85, 255),
                width=3,
            )
            draw.line(
                [(map_x0, y), (min(map_x1, map_x0 + tick_len * 4), y)],
                fill=(100, 116, 139, 180),
                width=2,
            )
            label = _format_coord(lat, False)
            # Center of vertical label sits in left collar
            label_cx = map_x0 - tick_len - (sample_th // 2) - 14
            _paste_vertical_label(
                canvas,
                label,
                cx=label_cx,
                cy=y,
                font=font_grid,
                fill=(15, 23, 42, 255),
            )
        lat += lat_step

    # ---- North arrow (large, top-right of map) ----
    na_h = max(90, short // 12)
    na_stem_w = max(6, short // 120)
    na_head_w = max(18, short // 45)
    na_head_h = max(28, short // 30)
    na_x = map_x1 - pad - max(36, short // 30)
    na_y = map_y0 + pad + 12
    # White backing plate
    plate_w = max(70, na_head_w * 3)
    plate_h = na_h + 40
    draw.rectangle(
        [
            na_x - plate_w // 2,
            na_y - 8,
            na_x + plate_w // 2,
            na_y + plate_h,
        ],
        fill=(255, 255, 255, 230),
        outline=(30, 41, 59, 255),
        width=2,
    )
    # Stem
    draw.line(
        [(na_x, na_y + na_h), (na_x, na_y + na_head_h - 4)],
        fill=(15, 23, 42, 255),
        width=na_stem_w,
    )
    # Arrow head
    draw.polygon(
        [
            (na_x, na_y),
            (na_x - na_head_w, na_y + na_head_h),
            (na_x + na_head_w, na_y + na_head_h),
        ],
        fill=(15, 23, 42, 255),
    )
    n_tw, n_th = _text_size(draw, "N", font_north)
    draw.text(
        (na_x - n_tw // 2, na_y + na_h + 4),
        "N",
        fill=(15, 23, 42, 255),
        font=font_north,
    )

    # ---- Scale bar (large, bottom-left of map) ----
    mid_lat = (south + north) / 2.0
    m_per_deg_lon = 111_320.0 * max(0.2, math.cos(math.radians(mid_lat)))
    map_width_m = lon_span * m_per_deg_lon
    scale_m = _nice_scale_m(map_width_m)
    scale_px = max(120, int(round((scale_m / map_width_m) * map_w)))
    scale_px = min(scale_px, map_w // 2)
    bar_h = max(16, short // 55)
    sb_x = map_x0 + pad
    sb_y = map_y1 - pad - bar_h - 36
    scale_label = f"Scale  {_format_scale_label(scale_m)}"
    sl_tw, sl_th = _text_size(draw, scale_label, font_scale)
    plate_right = max(sb_x + scale_px, sb_x + sl_tw) + 16
    draw.rectangle(
        [sb_x - 10, sb_y - sl_th - 14, plate_right, sb_y + bar_h + 14],
        fill=(255, 255, 255, 235),
        outline=(30, 41, 59, 255),
        width=2,
    )
    segs = 4
    seg_w = scale_px / segs
    for i in range(segs):
        x0 = sb_x + int(i * seg_w)
        x1 = sb_x + int((i + 1) * seg_w)
        fill = (15, 23, 42, 255) if i % 2 == 0 else (248, 250, 252, 255)
        draw.rectangle(
            [x0, sb_y, x1, sb_y + bar_h],
            fill=fill,
            outline=(15, 23, 42, 255),
            width=2,
        )
    draw.text(
        (sb_x, sb_y - sl_th - 6),
        scale_label,
        fill=(15, 23, 42, 255),
        font=font_scale,
    )

    # ---- Legend panel (right) with area km² — large type ----
    lx0 = map_x1 + pad
    ly0 = map_y0
    lx1 = canvas_w - pad
    ly1 = map_y1
    draw.rectangle(
        [lx0, ly0, lx1, ly1],
        fill=(248, 250, 252, 255),
        outline=(30, 41, 59, 255),
        width=3,
    )
    draw.text((lx0 + 18, ly0 + 16), "Legend", fill=(15, 23, 42, 255), font=font_legend_title)
    sub = "Class / Area (km²)"
    draw.text(
        (lx0 + 18, ly0 + 16 + (font_legend_title.size if hasattr(font_legend_title, "size") else 34) + 8),
        sub,
        fill=(71, 85, 105, 255),
        font=font_legend,
    )

    header_block = 16 + (font_legend_title.size if hasattr(font_legend_title, "size") else 34) + 8
    header_block += (font_legend.size if hasattr(font_legend, "size") else 26) + 20
    row_y = ly0 + header_block
    n_items = max(len(items), 1)
    avail = max(120, ly1 - ly0 - header_block - 70)
    row_h = max(48, min(72, avail // n_items))
    swatch = max(28, min(40, row_h - 16))

    for item in items:
        if row_y + row_h > ly1 - 56:
            break
        color = _hex_rgb(str(item.get("color") or "#888888"))
        label = str(item.get("label") or item.get("name") or "Class")
        area = item.get("area_km2")
        try:
            area_txt = f"{float(area):.3f}" if area is not None else "—"
        except (TypeError, ValueError):
            area_txt = "—"
        draw.rectangle(
            [lx0 + 18, row_y + 4, lx0 + 18 + swatch, row_y + 4 + swatch],
            fill=(*color, 255),
            outline=(15, 23, 42, 255),
            width=2,
        )
        text_x = lx0 + 18 + swatch + 12
        draw.text(
            (text_x, row_y),
            label[:24],
            fill=(15, 23, 42, 255),
            font=font_legend,
        )
        draw.text(
            (text_x, row_y + (font_legend.size if hasattr(font_legend, "size") else 26) + 4),
            f"{area_txt} km²",
            fill=(51, 65, 85, 255),
            font=font_legend,
        )
        row_y += row_h

    if total_area_km2 is not None:
        draw.line(
            [(lx0 + 14, ly1 - 52), (lx1 - 14, ly1 - 52)],
            fill=(148, 163, 184, 255),
            width=2,
        )
        total_txt = f"Total  {float(total_area_km2):.3f} km²"
        draw.text(
            (lx0 + 18, ly1 - 44),
            total_txt,
            fill=(15, 23, 42, 255),
            font=font_legend_title,
        )

    footer = "EarthVision Enterprise  ·  EPSG:4326  ·  Grid: left & bottom"
    fw, fh = _text_size(draw, footer, font_footer)
    draw.text(
        ((canvas_w - fw) // 2, canvas_h - fh - 10),
        footer,
        fill=(100, 116, 139, 255),
        font=font_footer,
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
