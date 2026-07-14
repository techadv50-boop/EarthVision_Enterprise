"""DEM generation and terrain analytics (slope, aspect, hillshade, contour, watershed, viewshed)."""

from __future__ import annotations

import base64
import io
import math
from typing import Any

import numpy as np
from loguru import logger
from PIL import Image
from shapely.geometry import LineString, mapping, shape

from app.core.exceptions import ValidationError
from app.schemas.analytics import ColormapStop, LegendInfo
from app.schemas.terrain import TerrainComputeRequest, TerrainComputeResponse


class TerrainService:
    """On-the-fly DEM and derived terrain products for the explorer map."""

    def compute(self, request: TerrainComputeRequest) -> TerrainComputeResponse:
        bounds = self._resolve_bounds(request.bbox, request.aoi)
        size = request.size
        dem = self._synthetic_dem(bounds, size)
        product = request.product

        if product == "dem":
            return self._product_dem(dem, bounds)
        if product == "slope":
            return self._product_raster(
                self._slope_deg(dem, bounds),
                bounds,
                "slope",
                "Slope (°)",
                "degrees",
                "terrain",
                "atan(√(dz/dx² + dz/dy²))",
                0,
                45,
            )
        if product == "aspect":
            return self._product_raster(
                self._aspect_deg(dem, bounds),
                bounds,
                "aspect",
                "Aspect (° from N)",
                "degrees",
                "aspect",
                "atan2(−dz/dx, dz/dy)",
                0,
                360,
            )
        if product == "hillshade":
            hs = self._hillshade(dem, bounds, request.azimuth_deg, request.altitude_deg)
            return self._product_raster(
                hs,
                bounds,
                "hillshade",
                "Hillshade",
                "shade 0–255",
                "gray",
                f"azimuth={request.azimuth_deg}° altitude={request.altitude_deg}°",
                0,
                255,
            )
        if product == "contour":
            return self._product_contour(dem, bounds, request.contour_interval)
        if product == "watershed":
            return self._product_watershed(dem, bounds)
        if product == "viewshed":
            return self._product_viewshed(dem, bounds, request)
        if product == "profile":
            return self._product_profile(dem, bounds, request)
        if product == "line_of_sight":
            return self._product_los(dem, bounds, request)
        if product == "flow_direction":
            return self._product_flow_direction(dem, bounds)
        if product == "flow_accumulation":
            return self._product_flow_accumulation(dem, bounds)
        if product == "ruggedness":
            return self._product_ruggedness(dem, bounds)
        if product == "cut_fill":
            return self._product_cut_fill(dem, bounds)
        raise ValidationError(f"Unsupported terrain product: {product}")

    def _resolve_bounds(
        self, bbox: list[float] | None, aoi: dict[str, Any] | None
    ) -> list[float]:
        if bbox and len(bbox) == 4:
            return [float(x) for x in bbox]
        if aoi:
            try:
                geom = shape(aoi if aoi.get("type") != "Feature" else aoi["geometry"])
                minx, miny, maxx, maxy = geom.bounds
                return [minx, miny, maxx, maxy]
            except Exception:  # noqa: BLE001
                pass
        return [74.15, 31.35, 74.55, 31.7]

    def _synthetic_dem(self, bounds: list[float], size: int) -> np.ndarray:
        """Multi-octave elevation surface (metres) for the AOI — demo DEM when no file uploaded."""
        west, south, east, north = bounds
        seed = abs(hash((round(west, 3), round(south, 3), round(east, 3), round(north, 3)))) % (
            2**31
        )
        rng = np.random.default_rng(seed)
        yy, xx = np.mgrid[0:size, 0:size]
        fx = xx / max(size - 1, 1)
        fy = yy / max(size - 1, 1)
        # Strong multi-ridge relief so 3D DEM under imagery has clear base height
        dem = (
            220
            + 860 * (1 - fx) * 0.48
            + 640 * (1 - fy) * 0.38
            + 210 * np.sin(fx * 6.4) * np.cos(fy * 4.8)
            + 140 * np.sin(fx * 14.0 + fy * 9.5)
            + 85 * np.cos(fx * 27.0 - fy * 18.0)
            + 45 * np.sin(fx * 41.0) * np.sin(fy * 33.0)
        )
        # Deeper river valley for visible relief contrast
        valley = np.exp(-((fx - 0.42) ** 2) / 0.01 - ((fy - 0.55) ** 2) / 0.08)
        dem -= 260 * valley
        peak = np.exp(-((fx - 0.68) ** 2) / 0.018 - ((fy - 0.28) ** 2) / 0.022)
        dem += 320 * peak
        dem += rng.normal(0, 3.5, dem.shape)
        return dem.astype(np.float64)

    def _pixel_size_m(self, bounds: list[float], size: int) -> tuple[float, float]:
        west, south, east, north = bounds
        lat_mid = (south + north) / 2
        dx = (east - west) / max(size - 1, 1) * 111_320.0 * math.cos(math.radians(lat_mid))
        dy = (north - south) / max(size - 1, 1) * 110_540.0
        return max(dx, 1e-3), max(dy, 1e-3)

    def _slope_deg(self, dem: np.ndarray, bounds: list[float]) -> np.ndarray:
        dx, dy = self._pixel_size_m(bounds, dem.shape[0])
        gy, gx = np.gradient(dem, dy, dx)
        return np.degrees(np.arctan(np.hypot(gx, gy)))

    def _aspect_deg(self, dem: np.ndarray, bounds: list[float]) -> np.ndarray:
        dx, dy = self._pixel_size_m(bounds, dem.shape[0])
        gy, gx = np.gradient(dem, dy, dx)
        aspect = np.degrees(np.arctan2(-gx, gy))
        aspect = np.where(aspect < 0, aspect + 360.0, aspect)
        return aspect

    def _hillshade(
        self, dem: np.ndarray, bounds: list[float], azimuth: float, altitude: float
    ) -> np.ndarray:
        dx, dy = self._pixel_size_m(bounds, dem.shape[0])
        gy, gx = np.gradient(dem, dy, dx)
        slope = np.arctan(np.hypot(gx, gy))
        aspect = np.arctan2(-gx, gy)
        az = math.radians(360.0 - azimuth + 90.0)
        alt = math.radians(altitude)
        shaded = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
        return np.clip(shaded * 255.0, 0, 255)

    def _colormap(
        self, name: str, t: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        t = np.clip(t, 0, 1)
        if name == "terrain":
            # green → yellow → brown → white
            r = np.clip(0.2 + 0.9 * t, 0, 1)
            g = np.clip(0.55 + 0.2 * t - 0.5 * (t > 0.7), 0, 1)
            b = np.clip(0.15 + 0.7 * np.maximum(t - 0.75, 0) / 0.25, 0, 1)
        elif name == "aspect":
            # HSV-like wheel
            ang = t * 2 * math.pi
            r = 0.5 + 0.5 * np.cos(ang)
            g = 0.5 + 0.5 * np.cos(ang - 2.094)
            b = 0.5 + 0.5 * np.cos(ang + 2.094)
        elif name == "gray":
            r = g = b = t
        elif name == "viewshed":
            r = 0.1 + 0.2 * t
            g = 0.35 + 0.55 * t
            b = 0.9 - 0.4 * t
        elif name == "watershed":
            # categorical-ish via hash of t
            r = (np.sin(t * 40) * 0.5 + 0.5) * 0.7 + 0.15
            g = (np.sin(t * 40 + 2) * 0.5 + 0.5) * 0.7 + 0.15
            b = (np.sin(t * 40 + 4) * 0.5 + 0.5) * 0.7 + 0.15
        elif name == "elev":
            r = np.clip(0.15 + 0.85 * t, 0, 1)
            g = np.clip(0.45 + 0.4 * (1 - abs(t - 0.45) * 2), 0, 1)
            b = np.clip(0.35 + 0.5 * (1 - t), 0, 1)
        elif name == "flow":
            r = 0.05 + 0.15 * t
            g = 0.25 + 0.55 * t
            b = 0.55 + 0.45 * t
        elif name == "tri":
            r = np.clip(0.3 + 0.7 * t, 0, 1)
            g = np.clip(0.55 - 0.2 * t, 0, 1)
            b = np.clip(0.2 + 0.1 * t, 0, 1)
        elif name == "cutfill":
            # blue = cut, red = fill
            r = np.where(t < 0.5, 0.15 + 0.3 * (t / 0.5), 0.55 + 0.45 * ((t - 0.5) / 0.5))
            g = np.where(t < 0.5, 0.35 + 0.4 * (t / 0.5), 0.75 - 0.55 * ((t - 0.5) / 0.5))
            b = np.where(t < 0.5, 0.85 - 0.2 * (t / 0.5), 0.35 - 0.25 * ((t - 0.5) / 0.5))
        else:
            r = g = b = t
        return np.clip(r, 0, 1), np.clip(g, 0, 1), np.clip(b, 0, 1)

    def _legend(self, label: str, unit: str, vmin: float, vmax: float, cmap: str) -> LegendInfo:
        stops: list[ColormapStop] = []
        for i in range(6):
            t = i / 5
            val = vmin + t * (vmax - vmin)
            r, g, b = self._colormap(cmap, np.array([t]))
            color = "#{:02x}{:02x}{:02x}".format(
                int(r[0] * 255), int(g[0] * 255), int(b[0] * 255)
            )
            stops.append(ColormapStop(value=float(val), color=color))
        return LegendInfo(min=float(vmin), max=float(vmax), unit=unit, label=label, formula="", stops=stops)

    def _rgba(
        self, array: np.ndarray, cmap: str, vmin: float, vmax: float, alpha: int = 200
    ) -> bytes:
        valid = np.isfinite(array)
        norm = np.zeros_like(array, dtype=float)
        norm[valid] = (array[valid] - vmin) / (vmax - vmin + 1e-12)
        r, g, b = self._colormap(cmap, norm)
        rgba = np.zeros((*array.shape, 4), dtype=np.uint8)
        rgba[..., 0] = (r * 255).astype(np.uint8)
        rgba[..., 1] = (g * 255).astype(np.uint8)
        rgba[..., 2] = (b * 255).astype(np.uint8)
        rgba[..., 3] = np.where(valid, alpha, 0).astype(np.uint8)
        buf = io.BytesIO()
        Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _product_dem(self, dem: np.ndarray, bounds: list[float]) -> TerrainComputeResponse:
        vmin, vmax = float(np.nanmin(dem)), float(np.nanmax(dem))
        # Elevation tint used as base under satellite (semi-transparent on client)
        png = self._rgba(dem, "elev", vmin, vmax, alpha=160)
        # Dense enough mesh for 3D under imagery (~48–64 cells)
        step = max(1, dem.shape[0] // 56)
        grid = dem[::step, ::step]
        relief = float(vmax - vmin)
        return TerrainComputeResponse(
            product="dem",
            bounds=bounds,
            overlay_base64=base64.b64encode(png).decode("ascii"),
            legend=self._legend("Elevation", "m", vmin, vmax, "elev"),
            dem_grid=np.round(grid, 1).tolist(),
            dem_stats={
                "min": vmin,
                "max": vmax,
                "mean": float(np.nanmean(dem)),
                "std": float(np.nanstd(dem)),
                "relief_m": relief,
            },
            formula="Synthetic DEM (demo) — upload GeoTIFF DEM for production",
            message=(
                f"DEM base placed under imagery · relief {relief:.0f} m · "
                "3D view enabled"
            ),
        )

    def _product_raster(
        self,
        arr: np.ndarray,
        bounds: list[float],
        product: str,
        label: str,
        unit: str,
        cmap: str,
        formula: str,
        vmin: float | None,
        vmax: float | None,
    ) -> TerrainComputeResponse:
        lo = float(np.nanpercentile(arr, 2)) if vmin is None else vmin
        hi = float(np.nanpercentile(arr, 98)) if vmax is None else vmax
        if product == "slope":
            hi = max(hi, 5.0)
        legend = self._legend(label, unit, lo, hi, cmap)
        legend.formula = formula
        png = self._rgba(arr, cmap, lo, hi)
        return TerrainComputeResponse(
            product=product,  # type: ignore[arg-type]
            bounds=bounds,
            overlay_base64=base64.b64encode(png).decode("ascii"),
            legend=legend,
            formula=formula,
        )

    def _product_contour(
        self, dem: np.ndarray, bounds: list[float], interval: float
    ) -> TerrainComputeResponse:
        west, south, east, north = bounds
        h, w = dem.shape
        zmin, zmax = float(np.nanmin(dem)), float(np.nanmax(dem))
        levels = np.arange(
            math.ceil(zmin / interval) * interval,
            zmax + interval * 0.5,
            interval,
        )
        features: list[dict[str, Any]] = []
        # Simple marching-squares-lite: horizontal/vertical zero crossings
        for level in levels:
            segs: list[list[list[float]]] = []
            for i in range(h - 1):
                for j in range(w - 1):
                    corners = [
                        dem[i, j],
                        dem[i, j + 1],
                        dem[i + 1, j + 1],
                        dem[i + 1, j],
                    ]
                    above = [c >= level for c in corners]
                    if all(above) or not any(above):
                        continue
                    # Edge midpoints where contour crosses
                    def edge_pt(a: int, b: int, ia: tuple[int, int], ib: tuple[int, int]) -> list[float]:
                        za, zb = corners[a], corners[b]
                        t = 0.0 if zb == za else (level - za) / (zb - za)
                        t = min(max(t, 0.0), 1.0)
                        row = ia[0] + t * (ib[0] - ia[0])
                        col = ia[1] + t * (ib[1] - ia[1])
                        lon = west + (col / (w - 1)) * (east - west)
                        lat = north - (row / (h - 1)) * (north - south)
                        return [lon, lat]

                    idxs = [(0, 1, (i, j), (i, j + 1)), (1, 2, (i, j + 1), (i + 1, j + 1)),
                            (2, 3, (i + 1, j + 1), (i + 1, j)), (3, 0, (i + 1, j), (i, j))]
                    pts = []
                    for a, b, ia, ib in idxs:
                        if above[a] != above[b]:
                            pts.append(edge_pt(a, b, ia, ib))
                    if len(pts) >= 2:
                        segs.append([pts[0], pts[1]])
            # Merge short segments into MultiLineString features (cap count)
            for seg in segs[:: max(1, len(segs) // 800 + 1)][:800]:
                features.append(
                    {
                        "type": "Feature",
                        "properties": {"elevation": float(level)},
                        "geometry": {"type": "LineString", "coordinates": seg},
                    }
                )
        # Also elevation tint underlay
        png = self._rgba(dem, "elev", zmin, zmax, alpha=90)
        return TerrainComputeResponse(
            product="contour",
            bounds=bounds,
            overlay_base64=base64.b64encode(png).decode("ascii"),
            legend=self._legend("Elevation", "m", zmin, zmax, "elev"),
            geojson={"type": "FeatureCollection", "features": features},
            formula=f"Contours every {interval} m",
            message=f"{len(features)} contour segments · interval {interval} m",
        )

    def _flow_direction(self, dem: np.ndarray) -> np.ndarray:
        """D8 flow direction codes 0–7 (E, SE, S, SW, W, NW, N, NE), -1 flat/pit."""
        h, w = dem.shape
        dirs = np.full((h, w), -1, dtype=np.int8)
        offsets = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]
        for i in range(1, h - 1):
            for j in range(1, w - 1):
                z = dem[i, j]
                best = 0.0
                best_d = -1
                for d, (di, dj) in enumerate(offsets):
                    drop = z - dem[i + di, j + dj]
                    dist = 1.414 if di and dj else 1.0
                    slope = drop / dist
                    if slope > best:
                        best = slope
                        best_d = d
                dirs[i, j] = best_d
        return dirs

    def _product_watershed(self, dem: np.ndarray, bounds: list[float]) -> TerrainComputeResponse:
        h, w = dem.shape
        dirs = self._flow_direction(dem)
        # Flow accumulation
        acc = np.ones((h, w), dtype=np.float64)
        order = np.argsort(dem.ravel())[::-1]  # high to low
        offsets = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]
        for idx in order:
            i, j = divmod(int(idx), w)
            d = int(dirs[i, j])
            if d < 0:
                continue
            di, dj = offsets[d]
            ni, nj = i + di, j + dj
            if 0 <= ni < h and 0 <= nj < w:
                acc[ni, nj] += acc[i, j]
        # Drainage lines where accumulation is high
        thresh = float(np.percentile(acc, 92))
        drainage = acc >= thresh
        # Catchment IDs via seeded region from local sinks
        catchment = np.zeros((h, w), dtype=np.float64)
        sinks = (dirs == -1)
        sink_ids = np.argwhere(sinks)
        for k, (si, sj) in enumerate(sink_ids[:64]):
            catchment[si, sj] = k + 1
        # Propagate uphill: reverse flow by assigning cell to downstream catchment
        for idx in order[::-1]:  # low to high
            i, j = divmod(int(idx), w)
            if catchment[i, j] > 0:
                continue
            d = int(dirs[i, j])
            if d < 0:
                continue
            di, dj = offsets[d]
            ni, nj = i + di, j + dj
            if 0 <= ni < h and 0 <= nj < w and catchment[ni, nj] > 0:
                catchment[i, j] = catchment[ni, nj]
        # Visualize catchments + drainage overlay emphasis
        vis = catchment / max(float(np.max(catchment)), 1.0)
        vis = np.where(drainage, np.minimum(vis + 0.35, 1.0), vis)
        png = self._rgba(vis, "watershed", 0, 1, alpha=190)
        # Drainage GeoJSON
        west, south, east, north = bounds
        features = []
        # Sample drainage pixels into line stubs
        ys, xs = np.where(drainage)
        for y, x in list(zip(ys.tolist(), xs.tolist()))[:: max(1, len(ys) // 400 + 1)][:400]:
            lon = west + (x / (w - 1)) * (east - west)
            lat = north - (y / (h - 1)) * (north - south)
            features.append(
                {
                    "type": "Feature",
                    "properties": {"kind": "drainage", "accumulation": float(acc[y, x])},
                    "geometry": {
                        "type": "Point",
                        "coordinates": [lon, lat],
                    },
                }
            )
        return TerrainComputeResponse(
            product="watershed",
            bounds=bounds,
            overlay_base64=base64.b64encode(png).decode("ascii"),
            legend=self._legend("Catchments", "id", 0, float(np.max(catchment) or 1), "watershed"),
            geojson={"type": "FeatureCollection", "features": features},
            formula="D8 flow · accumulation · catchment delineation",
            message=f"{int(np.max(catchment))} catchments · drainage threshold P92",
        )

    def _sample_dem(self, dem: np.ndarray, bounds: list[float], lon: float, lat: float) -> float:
        west, south, east, north = bounds
        h, w = dem.shape
        col = (lon - west) / (east - west + 1e-12) * (w - 1)
        row = (north - lat) / (north - south + 1e-12) * (h - 1)
        col = int(np.clip(round(col), 0, w - 1))
        row = int(np.clip(round(row), 0, h - 1))
        return float(dem[row, col])

    def _flow_accumulation(self, dem: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return (flow_direction, flow_accumulation)."""
        h, w = dem.shape
        dirs = self._flow_direction(dem)
        acc = np.ones((h, w), dtype=np.float64)
        order = np.argsort(dem.ravel())[::-1]
        offsets = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]
        for idx in order:
            i, j = divmod(int(idx), w)
            d = int(dirs[i, j])
            if d < 0:
                continue
            di, dj = offsets[d]
            ni, nj = i + di, j + dj
            if 0 <= ni < h and 0 <= nj < w:
                acc[ni, nj] += acc[i, j]
        return dirs, acc

    def _product_flow_direction(
        self, dem: np.ndarray, bounds: list[float]
    ) -> TerrainComputeResponse:
        dirs = self._flow_direction(dem).astype(np.float64)
        # Map -1 → nan for transparency at pits
        vis = np.where(dirs < 0, np.nan, dirs)
        return self._product_raster(
            vis,
            bounds,
            "flow_direction",
            "Flow direction (D8)",
            "code 0–7",
            "aspect",
            "D8: E,SE,S,SW,W,NW,N,NE",
            0,
            7,
        )

    def _product_flow_accumulation(
        self, dem: np.ndarray, bounds: list[float]
    ) -> TerrainComputeResponse:
        _dirs, acc = self._flow_accumulation(dem)
        log_acc = np.log1p(acc)
        return self._product_raster(
            log_acc,
            bounds,
            "flow_accumulation",
            "Flow accumulation",
            "log(cells+1)",
            "flow",
            "D8 flow accumulation (log1p)",
            None,
            None,
        )

    def _product_ruggedness(
        self, dem: np.ndarray, bounds: list[float]
    ) -> TerrainComputeResponse:
        """Terrain Ruggedness Index (Riley et al.) — mean absolute elevation difference vs 8 neighbours."""
        tri = np.zeros_like(dem)
        offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        for di, dj in offsets:
            shifted = np.roll(np.roll(dem, di, axis=0), dj, axis=1)
            tri += np.abs(dem - shifted)
        tri /= 8.0
        # Zero out edges (roll wraps)
        tri[0, :] = tri[-1, :] = tri[:, 0] = tri[:, -1] = np.nan
        return self._product_raster(
            tri,
            bounds,
            "ruggedness",
            "Ruggedness (TRI)",
            "m",
            "tri",
            "TRI = mean |z − z_neighbour| (8-neighbour)",
            None,
            None,
        )

    def _product_cut_fill(
        self, dem: np.ndarray, bounds: list[float]
    ) -> TerrainComputeResponse:
        """Simple cut/fill vs planar reference surface through DEM mean elevation."""
        ref = float(np.nanmean(dem))
        # Convention: + fill (dem below ref), − cut (dem above ref)
        cut_fill = ref - dem
        lo = float(np.nanpercentile(cut_fill, 2))
        hi = float(np.nanpercentile(cut_fill, 98))
        span = max(abs(lo), abs(hi), 1.0)
        png = self._rgba(cut_fill, "cutfill", -span, span)
        cut_vol = float(np.nansum(np.maximum(-cut_fill, 0)))
        fill_vol = float(np.nansum(np.maximum(cut_fill, 0)))
        dx, dy = self._pixel_size_m(bounds, dem.shape[0])
        cell = dx * dy
        return TerrainComputeResponse(
            product="cut_fill",
            bounds=bounds,
            overlay_base64=base64.b64encode(png).decode("ascii"),
            legend=self._legend("Cut / Fill", "m vs mean", -span, span, "cutfill"),
            dem_stats={
                "reference_m": ref,
                "cut_m_sum": cut_vol,
                "fill_m_sum": fill_vol,
                "cut_m3_approx": cut_vol * cell,
                "fill_m3_approx": fill_vol * cell,
            },
            formula=f"Δz = mean(DEM) − DEM  (ref={ref:.1f} m)",
            message=f"Cut≈{cut_vol * cell:.0f} m³ · Fill≈{fill_vol * cell:.0f} m³ (approx)",
        )

    def _product_viewshed(
        self, dem: np.ndarray, bounds: list[float], request: TerrainComputeRequest
    ) -> TerrainComputeResponse:
        west, south, east, north = bounds
        h, w = dem.shape
        if request.observer and len(request.observer) >= 2:
            olon, olat = float(request.observer[0]), float(request.observer[1])
        else:
            olon, olat = (west + east) / 2, (south + north) / 2
        oj = int(np.clip(round((olon - west) / (east - west + 1e-12) * (w - 1)), 0, w - 1))
        oi = int(np.clip(round((north - olat) / (north - south + 1e-12) * (h - 1)), 0, h - 1))
        z0 = dem[oi, oj] + request.observer_height_m
        visible = np.zeros((h, w), dtype=np.float64)
        visible[oi, oj] = 1.0
        # Ray cast to every cell (coarse but OK at 256)
        for i in range(h):
            for j in range(w):
                if i == oi and j == oj:
                    continue
                n_steps = max(abs(i - oi), abs(j - oj))
                if n_steps == 0:
                    continue
                clear = True
                target_z = dem[i, j]
                max_angle = -1e9
                for s in range(1, n_steps + 1):
                    t = s / n_steps
                    ri = oi + t * (i - oi)
                    rj = oj + t * (j - oj)
                    zi = dem[int(round(ri)), int(round(rj))]
                    dist = math.hypot(ri - oi, rj - oj) + 1e-6
                    angle = (zi - z0) / dist
                    if s < n_steps and angle > max_angle:
                        max_angle = angle
                    if s == n_steps:
                        # visible if line to target clears prior max horizon
                        tgt_angle = (target_z + request.target_height_m - z0) / dist
                        clear = tgt_angle >= max_angle - 1e-6
                visible[i, j] = 1.0 if clear else 0.0
        png = self._rgba(visible, "viewshed", 0, 1, alpha=180)
        return TerrainComputeResponse(
            product="viewshed",
            bounds=bounds,
            overlay_base64=base64.b64encode(png).decode("ascii"),
            legend=self._legend("Viewshed", "visible", 0, 1, "viewshed"),
            formula=f"Observer ({olon:.4f},{olat:.4f}) h={request.observer_height_m} m",
            message="On-the-fly viewshed · cyan = visible",
        )

    def _product_profile(
        self, dem: np.ndarray, bounds: list[float], request: TerrainComputeRequest
    ) -> TerrainComputeResponse:
        line = request.profile_line
        if not line:
            raise ValidationError("profile_line (GeoJSON LineString) is required")
        geom = shape(line if line.get("type") != "Feature" else line["geometry"])
        if geom.geom_type != "LineString":
            raise ValidationError("profile_line must be a LineString")
        coords = list(geom.coords)
        samples: list[dict[str, float]] = []
        dist = 0.0
        prev = coords[0]
        n = 80
        # densify
        densified: list[tuple[float, float]] = []
        for a, b in zip(coords[:-1], coords[1:]):
            for k in range(n // max(len(coords) - 1, 1)):
                t = k / max(n // max(len(coords) - 1, 1), 1)
                densified.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
        densified.append(coords[-1])
        for lon, lat in densified:
            z = self._sample_dem(dem, bounds, lon, lat)
            if samples:
                dlon = (lon - prev[0]) * 111_320 * math.cos(math.radians(lat))
                dlat = (lat - prev[1]) * 110_540
                dist += math.hypot(dlon, dlat)
            samples.append({"distance_m": dist, "elevation_m": z, "lon": lon, "lat": lat})
            prev = (lon, lat)
        return TerrainComputeResponse(
            product="profile",
            bounds=bounds,
            profile=samples,
            formula="3D elevation profile along line",
            message=f"{len(samples)} samples · length {dist:.0f} m",
        )

    def _product_los(
        self, dem: np.ndarray, bounds: list[float], request: TerrainComputeRequest
    ) -> TerrainComputeResponse:
        if not request.observer or not request.target:
            raise ValidationError("observer and target [lon,lat] required for line_of_sight")
        olon, olat = float(request.observer[0]), float(request.observer[1])
        tlon, tlat = float(request.target[0]), float(request.target[1])
        z0 = self._sample_dem(dem, bounds, olon, olat) + request.observer_height_m
        z1 = self._sample_dem(dem, bounds, tlon, tlat) + request.target_height_m
        # Sample along path
        n = 64
        blocked = False
        max_clearance = 1e9
        profile = []
        for i in range(n + 1):
            t = i / n
            lon = olon + t * (tlon - olon)
            lat = olat + t * (tlat - olat)
            ground = self._sample_dem(dem, bounds, lon, lat)
            ray = z0 + t * (z1 - z0)
            clearance = ray - ground
            max_clearance = min(max_clearance, clearance)
            if 0 < i < n and clearance < 0:
                blocked = True
            dist = t * math.hypot(
                (tlon - olon) * 111_320 * math.cos(math.radians(lat)),
                (tlat - olat) * 110_540,
            )
            profile.append(
                {
                    "distance_m": dist,
                    "elevation_m": ground,
                    "ray_m": ray,
                    "clearance_m": clearance,
                }
            )
        line = LineString([(olon, olat), (tlon, tlat)])
        return TerrainComputeResponse(
            product="line_of_sight",
            bounds=bounds,
            profile=profile,
            line_of_sight={
                "visible": not blocked,
                "min_clearance_m": float(max_clearance),
                "observer": [olon, olat],
                "target": [tlon, tlat],
            },
            geojson={
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"kind": "los", "visible": not blocked},
                        "geometry": mapping(line),
                    }
                ],
            },
            formula="Straight-line ray vs DEM",
            message="Visible" if not blocked else "Blocked by terrain",
        )
