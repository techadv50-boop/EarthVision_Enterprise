import { useEffect } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import type { MapOverlay } from '../store/workflowStore';

/**
 * Georeferenced 2.5D DEM mesh drawn under satellite imagery.
 * Elevations offset screen Y so CSS map tilt (view3d) reads as real terrain height.
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
      pane.style.zIndex = '415';
      pane.style.pointerEvents = 'none';
    }

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
    // Strong base height so terrain reads in 3D under the Eye-On image
    const exaggeration = overlay.exaggeration ?? 3.2;
    const maxPx = Math.max(56, Math.min(140, span * exaggeration * 0.12));

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

    const shade = (r: number, c: number) => {
      const z0 = elevAt(r, c);
      const zx = elevAt(r, c + 1);
      const zy = elevAt(r + 1, c);
      const t = (z0 - zmin) / span;
      // Simple lit relief from NW
      const lit = 0.55 + 0.45 * Math.tanh(((zx - z0) + (zy - z0)) / (span * 0.08 + 1e-6));
      const rCol = Math.floor(55 + 150 * t * lit);
      const gCol = Math.floor(95 + 90 * (1 - Math.abs(t - 0.45)) * lit);
      const bCol = Math.floor(55 + 35 * (1 - t) * lit);
      return `rgba(${rCol},${gCol},${bCol},0.78)`;
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

      // Draw back-to-front for a crude depth sort
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
          ctx.fillStyle = shade(r, c);
          ctx.fill();
          ctx.strokeStyle = 'rgba(20,40,30,0.18)';
          ctx.lineWidth = 0.4;
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
  }, [map, overlay, enabled]);

  return null;
}
