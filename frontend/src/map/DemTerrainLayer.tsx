import { useEffect } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import type { MapOverlay } from '../store/workflowStore';

/** Blue → cyan → yellow → red, matching backend elev legend. */
function elevRgb(t: number, lit: number): [number, number, number] {
  const x = Math.max(0, Math.min(1, t));
  const r = Math.min(255, Math.round((0.05 + 0.25 * x + 0.85 * x ** 1.4) * 255 * lit));
  const g = Math.min(
    255,
    Math.round((0.55 + 0.45 * x - 1.15 * Math.max(x - 0.5, 0)) * 255 * lit),
  );
  const b = Math.min(255, Math.round((0.95 - 0.9 * x) * 255 * lit));
  return [r, g, b];
}

/**
 * DEM elevation mesh drawn in evStackPane.
 * Uses elev color ramp only — satellite imagery comes from scene TileLayers stacked above.
 */
export function DemTerrainLayer({
  overlay,
  enabled = true,
  zIndex = 415,
}: {
  overlay: MapOverlay | null;
  enabled?: boolean;
  zIndex?: number;
}) {
  const map = useMap();

  useEffect(() => {
    const grid = overlay?.demGrid;
    if (!enabled || !overlay || !grid?.length || !grid[0]?.length) return;

    const paneName = 'evStackPane';
    let pane = map.getPane(paneName);
    if (!pane) {
      pane = map.createPane(paneName);
      pane.style.zIndex = '450';
      pane.style.pointerEvents = 'none';
    }

    const canvas = L.DomUtil.create('canvas', 'ev-dem-mesh') as HTMLCanvasElement;
    canvas.dataset.evId = overlay.id;
    canvas.style.position = 'absolute';
    canvas.style.left = '0';
    canvas.style.top = '0';
    canvas.style.pointerEvents = 'none';
    canvas.style.zIndex = String(zIndex);
    pane.appendChild(canvas);

    const [west, south, east, north] = overlay.bounds;
    const rows = grid.length;
    const cols = grid[0].length;
    let zmin = Infinity;
    let zmax = -Infinity;
    for (const row of grid) {
      for (const z of row) {
        if (Number.isFinite(z)) {
          if (z < zmin) zmin = z;
          if (z > zmax) zmax = z;
        }
      }
    }
    const span = Math.max(zmax - zmin, 1);
    // Soft plains extrusion — Base height slider scales this gently
    const exaggeration = Math.min(Math.max(overlay.exaggeration ?? 1.2, 0.5), 3.0);
    const maxPx = Math.min(16, Math.max(3, (span / 40) * 10 * exaggeration));

    const elevAt = (r: number, c: number) => {
      const rr = Math.max(0, Math.min(rows - 1, r));
      const cc = Math.max(0, Math.min(cols - 1, c));
      return grid[rr][cc];
    };

    const project = (r: number, c: number) => {
      const lon = west + (c / Math.max(cols - 1, 1)) * (east - west);
      const lat = north - (r / Math.max(rows - 1, 1)) * (north - south);
      const pt = map.latLngToLayerPoint([lat, lon]);
      const z = elevAt(r, c);
      const h = ((z - zmin) / span) * maxPx;
      return L.point(pt.x, pt.y - h);
    };

    const litAt = (r: number, c: number) => {
      const z0 = elevAt(r, c);
      const zx = elevAt(r, c + 1);
      const zy = elevAt(r + 1, c);
      const slope = Math.tanh(((zx - z0) + (zy - z0)) / (span * 0.35 + 1e-6));
      return 0.88 + 0.12 * slope;
    };

    const draw = () => {
      const size = map.getSize();
      const topLeft = map.containerPointToLayerPoint([0, 0]);
      canvas.width = size.x;
      canvas.height = size.y;
      L.DomUtil.setPosition(canvas, topLeft);
      // Keep stack id + z in sync after redraw
      canvas.dataset.evId = overlay.id;
      canvas.style.zIndex = String(zIndex);

      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.clearRect(0, 0, size.x, size.y);
      ctx.save();
      ctx.translate(-topLeft.x, -topLeft.y);

      for (let r = 0; r < rows - 1; r++) {
        for (let c = 0; c < cols - 1; c++) {
          const p0 = project(r, c);
          const p1 = project(r, c + 1);
          const p2 = project(r + 1, c + 1);
          const p3 = project(r + 1, c);
          ctx.beginPath();
          ctx.moveTo(p0.x, p0.y);
          ctx.lineTo(p1.x, p1.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.lineTo(p3.x, p3.y);
          ctx.closePath();

          const t = (elevAt(r, c) - zmin) / span;
          const [er, eg, eb] = elevRgb(t, litAt(r, c));
          ctx.fillStyle = `rgba(${er},${eg},${eb},0.92)`;
          ctx.fill();
          ctx.strokeStyle = 'rgba(20,40,60,0.06)';
          ctx.lineWidth = 0.25;
          ctx.stroke();
        }
      }
      ctx.restore();
    };

    draw();
    map.on('move zoom moveend zoomend viewreset', draw);
    return () => {
      map.off('move zoom moveend zoomend viewreset', draw);
      canvas.remove();
    };
  }, [map, overlay, enabled, zIndex]);

  return null;
}
