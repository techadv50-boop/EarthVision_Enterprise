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
 * DEM as a base height surface UNDER satellite tiles.
 * Mesh uses the elevation color ramp; optional soft satellite blend;
 * gentle extrusion so plains stay plains (not alpine spikes).
 */
export function DemTerrainLayer({
  overlay,
  enabled = true,
}: {
  overlay: MapOverlay | null;
  enabled?: boolean;
}) {
  const map = useMap();

  useEffect(() => {
    const grid = overlay?.demGrid;
    if (!enabled || !overlay || !grid?.length || !grid[0]?.length) return;

    const paneName = 'evDemMeshPane';
    let pane = map.getPane(paneName);
    if (!pane) {
      pane = map.createPane(paneName);
      pane.style.pointerEvents = 'none';
    }
    // Always UNDER Eye-On satellite (scene @ 430)
    pane.style.zIndex = '415';

    const canvas = L.DomUtil.create('canvas', 'ev-dem-mesh') as HTMLCanvasElement;
    canvas.style.position = 'absolute';
    canvas.style.left = '0';
    canvas.style.top = '0';
    canvas.style.pointerEvents = 'none';
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
    // Gentle exaggeration — plains relief stays subtle but readable
    const exaggeration = overlay.exaggeration ?? 1.6;
    const maxPx = Math.min(32, Math.max(10, (span / 35) * 20 * exaggeration));

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

    // Soft lighting only — never crush to black
    const litAt = (r: number, c: number) => {
      const z0 = elevAt(r, c);
      const zx = elevAt(r, c + 1);
      const zy = elevAt(r + 1, c);
      const slope = Math.tanh(((zx - z0) + (zy - z0)) / (span * 0.25 + 1e-6));
      return 0.82 + 0.18 * slope;
    };

    let cellSat: Array<Array<[number, number, number] | null>> | null = null;

    const buildSatColors = (img: HTMLImageElement) => {
      const off = document.createElement('canvas');
      off.width = img.naturalWidth || img.width;
      off.height = img.naturalHeight || img.height;
      const octx = off.getContext('2d', { willReadFrequently: true });
      if (!octx) return;
      octx.drawImage(img, 0, 0);
      const data = octx.getImageData(0, 0, off.width, off.height).data;
      cellSat = [];
      for (let r = 0; r < rows; r++) {
        const row: Array<[number, number, number] | null> = [];
        for (let c = 0; c < cols; c++) {
          const u = c / Math.max(cols - 1, 1);
          const v = r / Math.max(rows - 1, 1);
          const x = Math.min(off.width - 1, Math.max(0, Math.floor(u * (off.width - 1))));
          const y = Math.min(off.height - 1, Math.max(0, Math.floor(v * (off.height - 1))));
          const i = (y * off.width + x) * 4;
          row.push([data[i], data[i + 1], data[i + 2]]);
        }
        cellSat.push(row);
      }
    };

    const draw = () => {
      const size = map.getSize();
      const topLeft = map.containerPointToLayerPoint([0, 0]);
      canvas.width = size.x;
      canvas.height = size.y;
      L.DomUtil.setPosition(canvas, topLeft);

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
          const lit = litAt(r, c);
          const [er, eg, eb] = elevRgb(t, lit);
          const sat = cellSat?.[r]?.[c];
          if (sat) {
            // Elev color base + bright satellite blend (DEM under, image on top of base)
            const rr = Math.round(er * 0.38 + sat[0] * 0.62);
            const gg = Math.round(eg * 0.38 + sat[1] * 0.62);
            const bb = Math.round(eb * 0.38 + sat[2] * 0.62);
            ctx.fillStyle = `rgb(${rr},${gg},${bb})`;
          } else {
            ctx.fillStyle = `rgb(${er},${eg},${eb})`;
          }
          ctx.fill();
          ctx.strokeStyle = 'rgba(20,40,60,0.08)';
          ctx.lineWidth = 0.3;
          ctx.stroke();
        }
      }
      ctx.restore();
    };

    const start = () => {
      draw();
      map.on('move zoom moveend zoomend viewreset', draw);
    };

    if (overlay.textureUrl) {
      const texture = new Image();
      texture.crossOrigin = 'anonymous';
      texture.onload = () => {
        buildSatColors(texture);
        start();
      };
      texture.onerror = () => start();
      texture.src = overlay.textureUrl;
    } else {
      start();
    }

    return () => {
      map.off('move zoom moveend zoomend viewreset', draw);
      canvas.remove();
    };
  }, [map, overlay, enabled]);

  return null;
}
