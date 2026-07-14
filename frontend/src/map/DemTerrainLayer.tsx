import { useEffect } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import type { MapOverlay } from '../store/workflowStore';

/**
 * Georeferenced 2.5D DEM mesh.
 * When a satellite drape texture is present, samples imagery onto elevated cells
 * so heightwise variation appears ON the satellite surface under Eye-On imagery.
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
      // Above OSM; when draped, also above flat scene tiles (hidden) so mesh is the image
      pane.style.zIndex = overlay.textureUrl ? '435' : '415';
      pane.style.pointerEvents = 'none';
    } else {
      pane.style.zIndex = overlay.textureUrl ? '435' : '415';
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
    const exaggeration = overlay.exaggeration ?? 3.4;
    const maxPx = Math.max(64, Math.min(160, span * exaggeration * 0.14));

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
      return 0.45 + 0.55 * Math.tanh(((zx - z0) + (zy - z0)) / (span * 0.08 + 1e-6));
    };

    let texture: HTMLImageElement | null = null;
    // Precomputed RGB per cell from drape texture (avoids getImageData each frame)
    let cellRgb: Array<Array<[number, number, number] | null>> | null = null;

    const buildCellColors = (img: HTMLImageElement) => {
      const off = document.createElement('canvas');
      off.width = img.naturalWidth || img.width;
      off.height = img.naturalHeight || img.height;
      const octx = off.getContext('2d', { willReadFrequently: true });
      if (!octx) return;
      octx.drawImage(img, 0, 0);
      const data = octx.getImageData(0, 0, off.width, off.height).data;
      cellRgb = [];
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
        cellRgb.push(row);
      }
    };

    const elevFill = (r: number, c: number) => {
      const t = (elevAt(r, c) - zmin) / span;
      const lit = litAt(r, c);
      const rCol = Math.floor(55 + 150 * t * lit);
      const gCol = Math.floor(95 + 90 * (1 - Math.abs(t - 0.45)) * lit);
      const bCol = Math.floor(55 + 35 * (1 - t) * lit);
      return `rgba(${rCol},${gCol},${bCol},0.9)`;
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

          const rgb = cellRgb?.[r]?.[c] ?? null;
          if (rgb) {
            const lit = litAt(r, c);
            const rr = Math.min(255, Math.round(rgb[0] * lit));
            const gg = Math.min(255, Math.round(rgb[1] * lit));
            const bb = Math.min(255, Math.round(rgb[2] * lit));
            ctx.fillStyle = `rgb(${rr},${gg},${bb})`;
          } else {
            ctx.fillStyle = elevFill(r, c);
          }
          ctx.fill();
          ctx.strokeStyle = 'rgba(10,20,15,0.12)';
          ctx.lineWidth = 0.35;
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
      texture = new Image();
      texture.crossOrigin = 'anonymous';
      texture.onload = () => {
        buildCellColors(texture!);
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
