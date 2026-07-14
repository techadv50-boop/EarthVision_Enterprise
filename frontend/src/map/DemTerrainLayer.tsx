import { useEffect, useRef } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import type { MapOverlay } from '../store/workflowStore';

type RGB = [number, number, number];

function elevRgb(t: number, lit: number): RGB {
  const x = Math.max(0, Math.min(1, t));
  const r = Math.min(255, Math.round((0.1 + 0.2 * x + 0.85 * x ** 1.35) * 255 * lit));
  const g = Math.min(
    255,
    Math.round((0.45 + 0.5 * x - 1.1 * Math.max(x - 0.5, 0)) * 255 * lit),
  );
  const b = Math.min(255, Math.round((0.9 - 0.85 * x) * 255 * lit));
  return [r, g, b];
}

/**
 * ArcScene-style DEM: satellite texture draped on elevation mesh with
 * yaw / pitch / vertical exaggeration (painter-sorted canvas mesh).
 */
export function DemTerrainLayer({
  overlay,
  enabled = true,
  zIndex = 415,
  sceneTextureUrl = null,
}: {
  overlay: MapOverlay | null;
  enabled?: boolean;
  zIndex?: number;
  sceneTextureUrl?: string | null;
}) {
  const map = useMap();
  /** Pre-sampled texture grid aligned to DEM cells — [row][col] RGB */
  const texGridRef = useRef<RGB[][] | null>(null);
  const texKeyRef = useRef<string | null>(null);

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
    const exaggeration = Math.min(Math.max(overlay.exaggeration ?? 2.2, 0.5), 5.0);
    const yaw = ((overlay.demYaw ?? 32) * Math.PI) / 180;
    const pitchDeg = overlay.demPitch ?? 55;
    const pitch = Math.max(0.28, Math.min(0.92, pitchDeg / 90));

    const elevAt = (r: number, c: number) => {
      const rr = Math.max(0, Math.min(rows - 1, r));
      const cc = Math.max(0, Math.min(cols - 1, c));
      return grid[rr][cc];
    };

    const litAt = (r: number, c: number) => {
      const z0 = elevAt(r, c);
      const zx = elevAt(r, c + 1);
      const zy = elevAt(r + 1, c);
      const slope = Math.tanh(((zx - z0) + (zy - z0)) / (span * 0.28 + 1e-6));
      return 0.7 + 0.3 * slope;
    };

    const buildTexGrid = (img: HTMLImageElement): RGB[][] => {
      const off = document.createElement('canvas');
      off.width = cols;
      off.height = rows;
      const ctx = off.getContext('2d', { willReadFrequently: true });
      if (!ctx) return [];
      ctx.drawImage(img, 0, 0, cols, rows);
      const data = ctx.getImageData(0, 0, cols, rows).data;
      const out: RGB[][] = [];
      for (let r = 0; r < rows; r++) {
        const row: RGB[] = [];
        for (let c = 0; c < cols; c++) {
          const i = (r * cols + c) * 4;
          row.push([data[i], data[i + 1], data[i + 2]]);
        }
        out.push(row);
      }
      return out;
    };

    const texSrc = overlay.textureUrl || sceneTextureUrl || null;

    const draw = () => {
      const size = map.getSize();
      const topLeft = map.containerPointToLayerPoint([0, 0]);
      canvas.width = size.x;
      canvas.height = size.y;
      L.DomUtil.setPosition(canvas, topLeft);
      canvas.dataset.evId = overlay.id;
      canvas.style.zIndex = String(zIndex);

      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.clearRect(0, 0, size.x, size.y);
      ctx.save();
      ctx.translate(-topLeft.x, -topLeft.y);

      const midLat = (south + north) / 2;
      const midLon = (west + east) / 2;
      const pivot = map.latLngToLayerPoint([midLat, midLon]);
      const sw = map.latLngToLayerPoint([south, west]);
      const ne = map.latLngToLayerPoint([north, east]);
      const footprintW = Math.max(48, Math.hypot(ne.x - sw.x, ne.y - sw.y));
      // Strong ArcScene-like relief vs footprint
      const maxH = Math.min(footprintW * 0.62, 260) * (exaggeration / 2.2);

      const cosY = Math.cos(yaw);
      const sinY = Math.sin(yaw);
      const texGrid = texGridRef.current;

      type Pt = { x: number; y: number; depth: number };
      const project = (r: number, c: number): Pt => {
        const lon = west + (c / Math.max(cols - 1, 1)) * (east - west);
        const lat = north - (r / Math.max(rows - 1, 1)) * (north - south);
        const raw = map.latLngToLayerPoint([lat, lon]);
        const lx = raw.x - pivot.x;
        const ly = raw.y - pivot.y;
        const rx = lx * cosY - ly * sinY;
        const ry = lx * sinY + ly * cosY;
        const z = elevAt(r, c);
        const h = ((z - zmin) / span) * maxH;
        return {
          x: pivot.x + rx,
          y: pivot.y + ry * pitch - h,
          depth: ry * pitch - h * 0.12,
        };
      };

      type Cell = {
        p0: Pt;
        p1: Pt;
        p2: Pt;
        p3: Pt;
        depth: number;
        r: number;
        c: number;
      };
      const cells: Cell[] = [];
      for (let r = 0; r < rows - 1; r++) {
        for (let c = 0; c < cols - 1; c++) {
          const p0 = project(r, c);
          const p1 = project(r, c + 1);
          const p2 = project(r + 1, c + 1);
          const p3 = project(r + 1, c);
          cells.push({
            p0,
            p1,
            p2,
            p3,
            depth: (p0.depth + p1.depth + p2.depth + p3.depth) * 0.25,
            r,
            c,
          });
        }
      }
      cells.sort((a, b) => a.depth - b.depth);

      for (const cell of cells) {
        const { p0, p1, p2, p3, r, c } = cell;
        const lit = litAt(r, c);
        const sampled = texGrid?.[r]?.[c];
        let fill: string;
        if (sampled) {
          fill = `rgba(${Math.min(255, Math.round(sampled[0] * lit))},${Math.min(
            255,
            Math.round(sampled[1] * lit),
          )},${Math.min(255, Math.round(sampled[2] * lit))},0.99)`;
        } else {
          const t = (elevAt(r, c) - zmin) / span;
          const [er, eg, eb] = elevRgb(t, lit);
          fill = `rgba(${er},${eg},${eb},0.95)`;
        }

        ctx.beginPath();
        ctx.moveTo(p0.x, p0.y);
        ctx.lineTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.lineTo(p3.x, p3.y);
        ctx.closePath();
        ctx.fillStyle = fill;
        ctx.fill();
        ctx.strokeStyle = 'rgba(8,18,28,0.07)';
        ctx.lineWidth = 0.3;
        ctx.stroke();
      }

      ctx.restore();
    };

    const start = () => {
      if (!texSrc) {
        texGridRef.current = null;
        texKeyRef.current = null;
        draw();
        return;
      }
      if (texKeyRef.current === texSrc && texGridRef.current) {
        draw();
        return;
      }
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        texGridRef.current = buildTexGrid(img);
        texKeyRef.current = texSrc;
        draw();
      };
      img.onerror = () => {
        texGridRef.current = null;
        texKeyRef.current = null;
        draw();
      };
      img.src = texSrc;
    };

    start();
    map.on('move zoom moveend zoomend viewreset', draw);
    return () => {
      map.off('move zoom moveend zoomend viewreset', draw);
      canvas.remove();
    };
  }, [map, overlay, enabled, zIndex, sceneTextureUrl]);

  return null;
}
