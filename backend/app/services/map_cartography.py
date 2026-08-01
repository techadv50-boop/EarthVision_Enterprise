"""Cartographic decorations for map-sheet GeoTIFF / PNG exports.

Adds north arrow, scale bar, left+bottom coordinate ticks/grid, and a legend
(with area in km²) around a georeferenced classification overlay.

Typography uses EB Garamond with generous spacing so labels never collide
with ticks, frames, or each other.
"""

from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageDraw, ImageFont

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_GARAMOND = {
    "regular": (
        _FONT_DIR / "EBGaramond12-Regular.ttf",
        Path("/usr/share/fonts/truetype/ebgaramond/EBGaramond12-Regular.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
    ),
    "bold": (
        _FONT_DIR / "EBGaramond12-Bold.ttf",
        Path("/usr/share/fonts/truetype/ebgaramond/EBGaramond12-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
    ),
    "italic": (
        _FONT_DIR / "EBGaramond12-Italic.ttf",
        Path("/usr/share/fonts/truetype/ebgaramond/EBGaramond12-Italic.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
    ),
}


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


def _font(size: int, weight: Literal["regular", "bold", "italic"] = "regular") -> ImageFont.ImageFont:
    for path in _GARAMOND[weight]:
        try:
            if path.is_file():
                return ImageFont.truetype(str(path), size=size)
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
    return f"{abs(value):.3f}° {hemi}"


def _grid_step(span: float) -> float:
    """Nice tick step for a geographic span in degrees."""
    if span <= 0:
        return 0.01
    raw = span / 4.5
    exp = math.floor(math.log10(raw))
    base = 10**exp
    for mult in (1, 2, 5, 10):
        if mult * base >= raw * 0.7:
            return float(mult * base)
    return float(10 * base)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return max(1, bbox[2] - bbox[0]), max(1, bbox[3] - bbox[1])


def _render_vertical_label(
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int] = (30, 41, 59, 255),
) -> Image.Image:
    """Render text rotated 90° CCW (reads upward)."""
    tmp = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    tw, th = _text_size(ImageDraw.Draw(tmp), text, font)
    pad = 3
    label_img = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(label_img).text((pad, pad), text, fill=fill, font=font)
    return label_img.rotate(90, expand=True, resample=Image.Resampling.BICUBIC)


def _paste_vertical_label_right_aligned(
    canvas: Image.Image,
    text: str,
    *,
    right: int,
    cy: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int] = (30, 41, 59, 255),
) -> None:
    """Paste a vertical label so its right edge sits at ``right`` (clear of ticks)."""
    rotated = _render_vertical_label(text, font, fill)
    rw, rh = rotated.size
    x0 = int(right - rw)
    y0 = int(cy - rh / 2)
    canvas.paste(rotated, (x0, y0), rotated)


def _collect_ticks(start: float, end: float, step: float) -> list[float]:
    values: list[float] = []
    v0 = math.ceil((start - 1e-12) / step) * step
    v = v0
    while v <= end + 1e-12:
        if start - 1e-9 <= v <= end + 1e-9:
            values.append(float(v))
        v += step
        if len(values) > 40:
            break
    return values


def _thin_ticks_by_spacing(
    ticks: list[float],
    to_px: Any,
    min_gap: float,
) -> list[float]:
    """Keep only ticks whose pixel centers are at least min_gap apart."""
    if not ticks:
        return []
    kept = [ticks[0]]
    last_px = to_px(ticks[0])
    for t in ticks[1:]:
        px = to_px(t)
        if abs(px - last_px) >= min_gap:
            kept.append(t)
            last_px = px
    return kept


def decorate_classification_map(
    png_bytes: bytes,
    bounds: list[float],
    legend_items: list[dict[str, Any]],
    *,
    title: str = "Land Cover Classification",
    total_area_km2: float | None = None,
) -> tuple[bytes, list[float]]:
    """Compose a map sheet with cartography; return PNG + extended geo bounds.

    Aesthetic rules:
      - EB Garamond throughout
      - Centered title with clear air below
      - Vertical left lat labels, horizontal bottom lon labels
      - Labels never touch ticks, frame, or each other
      - Legend / north arrow / scale bar sized and padded for readability
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

    # ---- Elegant Garamond scale (readable at 100%, with air around text) ----
    sz_title = max(36, min(48, short // 30))
    sz_grid = max(22, min(28, short // 50))
    sz_legend = max(22, min(26, short // 52))
    sz_legend_title = max(28, min(34, short // 40))
    sz_scale = max(22, min(26, short // 52))
    sz_north = max(30, min(38, short // 38))
    sz_footer = max(14, min(18, short // 70))

    font_title = _font(sz_title, "bold")
    font_grid = _font(sz_grid, "regular")
    font_legend = _font(sz_legend, "regular")
    font_legend_title = _font(sz_legend_title, "bold")
    font_legend_sub = _font(max(17, sz_legend - 2), "italic")
    font_scale = _font(sz_scale, "regular")
    font_north = _font(sz_north, "bold")
    font_footer = _font(sz_footer, "italic")

    # Spacing — keep every label clearly clear of ticks / frame / neighbors
    gap_label_tick = max(36, short // 32)  # air between tick tip and nearest glyph
    gap_label_label = max(32, sz_grid + 16)  # min gap between adjacent labels
    pad = max(44, short // 24)
    tick_len = max(14, short // 70)
    stub_len = max(10, short // 95)  # short inward stubs only
    frame_w = 2

    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    sample_lat = _format_coord((south + north) / 2.0, False)
    sample_lon = _format_coord((west + east) / 2.0, True)
    # Measure actual rotated label footprint for accurate collar sizing
    sample_rot = _render_vertical_label(sample_lat, font_grid)
    rot_w, rot_h = sample_rot.size
    lon_tw, lon_th = _text_size(probe, sample_lon, font_grid)
    left_margin = tick_len + gap_label_tick + rot_w + pad
    title_h = sz_title + pad + 56  # generous air under title before map frame
    bottom_h = tick_len + gap_label_tick + lon_th + pad + 24

    items = legend_items or []
    # Legend width for single-line "Class …… area" rows
    legend_inner_pad = 32
    swatch = max(22, min(28, sz_legend + 2))
    longest_label = "Cropland"
    longest_area = "999.999 km²"
    for it in items:
        lab = str(it.get("label") or it.get("name") or "Class")
        if len(lab) > len(longest_label):
            longest_label = lab
        try:
            at = f"{float(it.get('area_km2') or 0):.3f} km²"
            if len(at) > len(longest_area):
                longest_area = at
        except (TypeError, ValueError):
            pass
    lab_w, _ = _text_size(probe, longest_label[:22], font_legend)
    area_w, _ = _text_size(probe, longest_area, font_legend)
    legend_w = max(
        340,
        legend_inner_pad * 2 + swatch + 16 + lab_w + 28 + area_w + 8,
    )
    legend_w = min(legend_w, max(360, map_w // 2))

    canvas_w = left_margin + map_w + legend_w + pad * 2
    canvas_h = title_h + map_h + bottom_h + pad
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    map_x0 = left_margin
    map_y0 = title_h
    map_x1 = map_x0 + map_w
    map_y1 = map_y0 + map_h

    # ---- Centered title (clear of map frame) ----
    tw, th = _text_size(draw, title, font_title)
    # Sit title in upper half of title band so bottom air remains under it
    draw.text(
        ((canvas_w - tw) // 2, max(16, (title_h - th) // 3)),
        title,
        fill=(15, 23, 42, 255),
        font=font_title,
    )

    canvas.paste(map_img, (map_x0, map_y0), map_img)
    draw.rectangle(
        [map_x0 - 1, map_y0 - 1, map_x1, map_y1],
        outline=(51, 65, 85, 255),
        width=frame_w,
    )

    lon_span = east - west
    lat_span = north - south
    lon_step = _grid_step(lon_span)
    lat_step = _grid_step(lat_span)

    def lon_to_x(lon: float) -> int:
        return int(round(map_x0 + (lon - west) / lon_span * map_w))

    def lat_to_y(lat: float) -> int:
        return int(round(map_y0 + (north - lat) / lat_span * map_h))

    # Thin ticks so labels never overlap
    lon_ticks = _thin_ticks_by_spacing(
        _collect_ticks(west, east, lon_step),
        lon_to_x,
        min_gap=lon_tw + gap_label_label,
    )
    lat_ticks = _thin_ticks_by_spacing(
        _collect_ticks(south, north, lat_step),
        lat_to_y,
        min_gap=rot_h + gap_label_label,  # rotated label height
    )

    # Skip edge ticks that would crowd corners
    edge_pad_x = lon_tw * 0.65
    edge_pad_y = rot_h * 0.55
    lon_ticks = [
        t
        for t in lon_ticks
        if map_x0 + edge_pad_x <= lon_to_x(t) <= map_x1 - edge_pad_x
    ]
    lat_ticks = [
        t
        for t in lat_ticks
        if map_y0 + edge_pad_y <= lat_to_y(t) <= map_y1 - edge_pad_y
    ]

    # Bottom lon ticks + labels (text top sits gap below tick tip)
    for lon in lon_ticks:
        x = lon_to_x(lon)
        draw.line(
            [(x, map_y1), (x, map_y1 + tick_len)],
            fill=(71, 85, 105, 255),
            width=2,
        )
        draw.line(
            [(x, map_y1), (x, map_y1 - stub_len)],
            fill=(148, 163, 184, 140),
            width=1,
        )
        label = _format_coord(lon, True)
        ltw, _lth = _text_size(draw, label, font_grid)
        draw.text(
            (x - ltw // 2, map_y1 + tick_len + gap_label_tick),
            label,
            fill=(30, 41, 59, 255),
            font=font_grid,
        )

    # Left lat ticks + vertical labels (right edge of text = tick tip − gap)
    label_right = map_x0 - tick_len - gap_label_tick
    for lat in lat_ticks:
        y = lat_to_y(lat)
        draw.line(
            [(map_x0 - tick_len, y), (map_x0, y)],
            fill=(71, 85, 105, 255),
            width=2,
        )
        draw.line(
            [(map_x0, y), (map_x0 + stub_len, y)],
            fill=(148, 163, 184, 140),
            width=1,
        )
        _paste_vertical_label_right_aligned(
            canvas,
            _format_coord(lat, False),
            right=label_right,
            cy=y,
            font=font_grid,
            fill=(30, 41, 59, 255),
        )

    # ---- North arrow (top-right), clear of frame & stubs ----
    na_margin = max(pad, stub_len + 16)
    na_h = max(70, min(110, short // 14))
    na_head_w = max(14, na_h // 5)
    na_head_h = max(22, na_h // 3)
    na_stem_w = max(4, na_h // 18)
    n_tw, n_th = _text_size(draw, "N", font_north)
    plate_w = max(n_tw + 36, na_head_w * 2 + 36)
    plate_h = na_h + n_th + 40
    na_x = map_x1 - na_margin - plate_w // 2
    na_top = map_y0 + na_margin
    draw.rounded_rectangle(
        [na_x - plate_w // 2, na_top, na_x + plate_w // 2, na_top + plate_h],
        radius=6,
        fill=(255, 255, 255, 236),
        outline=(71, 85, 105, 255),
        width=1,
    )
    tip_y = na_top + 18
    stem_bot = tip_y + na_h - 8
    draw.line(
        [(na_x, stem_bot), (na_x, tip_y + na_head_h - 2)],
        fill=(15, 23, 42, 255),
        width=na_stem_w,
    )
    draw.polygon(
        [
            (na_x, tip_y),
            (na_x - na_head_w, tip_y + na_head_h),
            (na_x + na_head_w, tip_y + na_head_h),
        ],
        fill=(15, 23, 42, 255),
    )
    draw.text(
        (na_x - n_tw // 2, stem_bot + 10),
        "N",
        fill=(15, 23, 42, 255),
        font=font_north,
    )

    # ---- Scale bar (bottom-left), clear of ticks/stubs ----
    mid_lat = (south + north) / 2.0
    m_per_deg_lon = 111_320.0 * max(0.2, math.cos(math.radians(mid_lat)))
    map_width_m = lon_span * m_per_deg_lon
    scale_m = _nice_scale_m(map_width_m)
    scale_px = max(100, int(round((scale_m / map_width_m) * map_w)))
    scale_px = min(scale_px, map_w // 3)
    bar_h = max(12, min(18, short // 70))
    scale_label = f"Scale   {_format_scale_label(scale_m)}"
    sl_tw, sl_th = _text_size(draw, scale_label, font_scale)
    sb_margin = max(pad, stub_len + 16)
    sb_x = map_x0 + sb_margin
    plate_w_s = max(scale_px, sl_tw) + 40
    plate_h_s = sl_th + bar_h + 44
    sb_y = map_y1 - sb_margin - plate_h_s
    draw.rounded_rectangle(
        [sb_x, sb_y, sb_x + plate_w_s, sb_y + plate_h_s],
        radius=6,
        fill=(255, 255, 255, 236),
        outline=(71, 85, 105, 255),
        width=1,
    )
    label_x = sb_x + 20
    label_y = sb_y + 18
    draw.text((label_x, label_y), scale_label, fill=(15, 23, 42, 255), font=font_scale)
    bar_x = sb_x + 20
    bar_y = label_y + sl_th + 14
    segs = 4
    seg_w = scale_px / segs
    for i in range(segs):
        x0 = bar_x + int(i * seg_w)
        x1 = bar_x + int((i + 1) * seg_w)
        fill = (15, 23, 42, 255) if i % 2 == 0 else (248, 250, 252, 255)
        draw.rectangle(
            [x0, bar_y, x1, bar_y + bar_h],
            fill=fill,
            outline=(15, 23, 42, 255),
            width=1,
        )

    # ---- Legend panel (single-line rows: swatch · class · area) ----
    lx0 = map_x1 + pad
    ly0 = map_y0
    lx1 = canvas_w - pad
    ly1 = map_y1
    draw.rounded_rectangle(
        [lx0, ly0, lx1, ly1],
        radius=4,
        fill=(250, 250, 249, 255),
        outline=(71, 85, 105, 255),
        width=frame_w,
    )

    hx = lx0 + legend_inner_pad
    hy = ly0 + legend_inner_pad + 4
    draw.text((hx, hy), "Legend", fill=(15, 23, 42, 255), font=font_legend_title)
    _, lth = _text_size(draw, "Legend", font_legend_title)
    hy2 = hy + lth + 16
    draw.text(
        (hx, hy2),
        "Class  /  Area (km²)",
        fill=(71, 85, 105, 255),
        font=font_legend_sub,
    )
    _, sth = _text_size(draw, "Class  /  Area (km²)", font_legend_sub)
    # Divider well below subtitle
    div_y = hy2 + sth + 20
    draw.line([(lx0 + 24, div_y), (lx1 - 24, div_y)], fill=(203, 213, 225, 255), width=1)

    n_items = max(len(items), 1)
    footer_reserve = max(96, sz_legend_title + legend_inner_pad + 40)
    body_top = div_y + 28
    body_bot = ly1 - footer_reserve
    avail = max(140, body_bot - body_top)

    row_content = max(swatch, sz_legend + 6)
    # Even vertical rhythm with clear gaps between rows
    row_h = max(row_content + 22, avail // n_items)

    row_y = body_top
    area_right = lx1 - legend_inner_pad
    for item in items:
        if row_y + row_content > body_bot:
            break
        color = _hex_rgb(str(item.get("color") or "#888888"))
        label = str(item.get("label") or item.get("name") or "Class")[:22]
        area = item.get("area_km2")
        try:
            area_txt = f"{float(area):.3f} km²" if area is not None else "— km²"
        except (TypeError, ValueError):
            area_txt = "— km²"

        sw_y = row_y + max(0, (row_content - swatch) // 2)
        draw.rounded_rectangle(
            [hx, sw_y, hx + swatch, sw_y + swatch],
            radius=3,
            fill=(*color, 255),
            outline=(30, 41, 59, 255),
            width=1,
        )
        tx = hx + swatch + 16
        text_y = row_y + max(0, (row_content - sz_legend) // 2 - 2)
        draw.text((tx, text_y), label, fill=(15, 23, 42, 255), font=font_legend)
        atw, _ = _text_size(draw, area_txt, font_legend)
        draw.text(
            (area_right - atw, text_y),
            area_txt,
            fill=(71, 85, 105, 255),
            font=font_legend,
        )
        row_y += row_h

    if total_area_km2 is not None:
        tot_txt = f"Total   {float(total_area_km2):.3f} km²"
        _, tth = _text_size(draw, tot_txt, font_legend_title)
        tot_y = ly1 - legend_inner_pad - tth - 4
        draw.line(
            [(lx0 + 24, tot_y - 24), (lx1 - 24, tot_y - 24)],
            fill=(203, 213, 225, 255),
            width=1,
        )
        draw.text((hx, tot_y), tot_txt, fill=(15, 23, 42, 255), font=font_legend_title)

    footer = "EarthVision Enterprise  ·  EPSG:4326  ·  Grid: left & bottom"
    fw, fh = _text_size(draw, footer, font_footer)
    draw.text(
        ((canvas_w - fw) // 2, canvas_h - fh - 10),
        footer,
        fill=(100, 116, 139, 255),
        font=font_footer,
    )

    # Extended geographic bounds so map pixels keep correct geotransform
    px_w = lon_span / map_w
    px_h = lat_span / map_h
    ext_west = west - map_x0 * px_w
    ext_north = north + map_y0 * px_h
    ext_east = ext_west + canvas_w * px_w
    ext_south = ext_north - canvas_h * px_h

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", compress_level=6)
    return buf.getvalue(), [ext_west, ext_south, ext_east, ext_north]
