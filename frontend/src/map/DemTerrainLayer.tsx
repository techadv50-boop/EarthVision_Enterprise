import { useEffect, useRef } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import type { MapOverlay } from '../store/workflowStore';

type RGB = [number, number, number];

export type DemColormapId =
  | 'elev'
  | 'terrain'
  | 'viridis'
  | 'plasma'
  | 'inferno'
  | 'turbo'
  | 'grayscale'
  | 'coolwarm';

export const DEM_COLORMAPS: Array<{
  id: DemColormapId;
  label: string;
  /** CSS gradient preview */
  gradient: string;
}> = [
  {
    id: 'elev',
    label: 'Elevation',
    gradient: 'linear-gradient(90deg,#08306b,#41b6c4,#ffffb2,#fd8d3c,#b10026)',
  },
  {
    id: 'terrain',
    label: 'Terrain',
    gradient: 'linear-gradient(90deg,#2d6a4f,#95d5b2,#f4e285,#d08c60,#6f1d1b)',
  },
  {
    id: 'viridis',
    label: 'Viridis',
    gradient: 'linear-gradient(90deg,#440154,#31688e,#35b779,#fde725)',
  },
  {
    id: 'plasma',
    label: 'Plasma',
    gradient: 'linear-gradient(90deg,#0d0887,#cc4778,#f0f921)',
  },
  {
    id: 'inferno',
    label: 'Inferno',
    gradient: 'linear-gradient(90deg,#000004,#912c5c,#fb9b06,#fcffa4)',
  },
  {
    id: 'turbo',
    label: 'Turbo',
    gradient: 'linear-gradient(90deg,#30123b,#1ae4b6,#faba39,#7a0403)',
  },
  {
    id: 'grayscale',
    label: 'Gray',
    gradient: 'linear-gradient(90deg,#111,#888,#f5f5f5)',
  },
  {
    id: 'coolwarm',
    label: 'Cool–Warm',
    gradient: 'linear-gradient(90deg,#3b4cc0,#dddcdc,#b40426)',
  },
];

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

function lerpRgb(a: RGB, b: RGB, t: number): RGB {
  return [
    Math.round(lerp(a[0], b[0], t)),
    Math.round(lerp(a[1], b[1], t)),
    Math.round(lerp(a[2], b[2], t)),
  ];
}

/** Piecewise colormap stops in 0–1 → RGB */
const STOPS: Record<DemColormapId, Array<[number, RGB]>> = {
  elev: [
    [0, [8, 48, 107]],
    [0.25, [65, 182, 196]],
    [0.5, [255, 255, 178]],
    [0.75, [253, 141, 60]],
    [1, [177, 0, 38]],
  ],
  terrain: [
    [0, [45, 106, 79]],
    [0.3, [149, 213, 178]],
    [0.55, [244, 226, 133]],
    [0.8, [208, 140, 96]],
    [1, [111, 29, 27]],
  ],
  viridis: [
    [0, [68, 1, 84]],
    [0.33, [49, 104, 142]],
    [0.66, [53, 183, 121]],
    [1, [253, 231, 37]],
  ],
  plasma: [
    [0, [13, 8, 135]],
    [0.5, [204, 71, 120]],
    [1, [240, 249, 33]],
  ],
  inferno: [
    [0, [0, 0, 4]],
    [0.4, [145, 44, 92]],
    [0.75, [251, 155, 6]],
    [1, [252, 255, 164]],
  ],
  turbo: [
    [0, [48, 18, 59]],
    [0.35, [26, 228, 182]],
    [0.7, [250, 186, 57]],
    [1, [122, 4, 3]],
  ],
  grayscale: [
    [0, [20, 20, 20]],
    [1, [245, 245, 245]],
  ],
  coolwarm: [
    [0, [59, 76, 192]],
    [0.5, [221, 221, 221]],
    [1, [180, 4, 38]],
  ],
};

export function sampleDemColormap(id: DemColormapId, t: number, lit = 1): RGB {
  const x = Math.max(0, Math.min(1, t));
  const stops = STOPS[id] || STOPS.elev;
  let i = 0;
  while (i < stops.length - 1 && x > stops[i + 1][0]) i += 1;
  const [t0, c0] = stops[i];
  const [t1, c1] = stops[Math.min(i + 1, stops.length - 1)];
  const u = t1 === t0 ? 0 : (x - t0) / (t1 - t0);
  const [r, g, b] = lerpRgb(c0, c1, u);
  return [
    Math.min(255, Math.round(r * lit)),
    Math.min(255, Math.round(g * lit)),
    Math.min(255, Math.round(b * lit)),
  ];
}

/**
 * DEM elevation mesh rendered in a dedicated lower pane (behind imagery).
 * Uses selectable elevation color themes so relief reads under the satellite.
 */
export function DemTerrainLayer({
  overlay,
  enabled = true,
  zIndex = 405,
}: {
  overlay: MapOverlay | null;
  enabled?: boolean;
  zIndex?: number;
}) {
  const map = useMap();
  const texGridRef = useRef<RGB[][] | null>(null);
  const texKeyRef = useRef<string | null>(null);

  useEffect(() => {
    const grid = overlay?.demGrid;
    if (!enabled || !overlay || !grid?.length || !grid[0]?.length) return;

    // Dedicated DEM pane BELOW imagery stack — guarantees DEM stays behind satellite
    const paneName = 'evDemPane';
    let pane = map.getPane(paneName);
    if (!pane) {
      pane = map.createPane(paneName);
      pane.style.zIndex = '440';
      pane.style.pointerEvents = 'none';
    }
    // Imagery stack must sit above DEM pane
    let stack = map.getPane('evStackPane');
    if (!stack) {
      stack = map.createPane('evStackPane');
      stack.style.zIndex = '450';
      stack.style.pointerEvents = 'none';
    } else {
      stack.style.zIndex = '450';
    }

    const canvas = L.DomUtil.create('canvas', 'ev-dem-mesh') as HTMLCanvasElement;
    canvas.dataset.evId = overlay.id;
    canvas.dataset.evDem = '1';
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
    const exaggeration = Math.min(Math.max(overlay.exaggeration ?? 2.0, 0.4), 5.0);
    const yaw = ((overlay.demYaw ?? 18) * Math.PI) / 180;
    const pitchDeg = overlay.demPitch ?? 72;
    const pitch = Math.max(0.35, Math.min(0.98, pitchDeg / 90));
    const cmap = (overlay.demColormap as DemColormapId) || 'elev';
    // How much satellite texture tints the elev colors (0 = pure elev theme)
    const texMix = Math.min(Math.max(overlay.demTextureMix ?? 0.15, 0), 0.5);
    const meshOpacity = Math.min(Math.max(overlay.opacity ?? 0.92, 0.2), 1);

    const elevAt = (r: number, c: number) => {
      const rr = Math.max(0, Math.min(rows - 1, r));
      const cc = Math.max(0, Math.min(cols - 1, c));
      return grid[rr][cc];
    };

    const litAt = (r: number, c: number) => {
      const z0 = elevAt(r, c);
      const zx = elevAt(r, c + 1);
      const zy = elevAt(r + 1, c);
      const slope = Math.tanh(((zx - z0) * 1.15 + (zy - z0) * 0.95) / (span * 0.2 + 1e-6));
      return 0.58 + 0.42 * slope;
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
      ctx.globalAlpha = meshOpacity;

      const midLat = (south + north) / 2;
      const midLon = (west + east) / 2;
      const pivot = map.latLngToLayerPoint([midLat, midLon]);
      const sw = map.latLngToLayerPoint([south, west]);
      const ne = map.latLngToLayerPoint([north, east]);
      const footprintW = Math.max(48, Math.hypot(ne.x - sw.x, ne.y - sw.y));
      const maxH = Math.min(footprintW * 0.48, 200) * (exaggeration / 2.2);

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
          depth: ry * pitch - h * 0.1,
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
        const t = (elevAt(r, c) - zmin) / span;
        let [er, eg, eb] = sampleDemColormap(cmap, t, lit);
        const sampled = texGrid?.[r]?.[c];
        if (sampled && texMix > 0) {
          er = Math.round(er * (1 - texMix) + sampled[0] * lit * texMix);
          eg = Math.round(eg * (1 - texMix) + sampled[1] * lit * texMix);
          eb = Math.round(eb * (1 - texMix) + sampled[2] * lit * texMix);
        }

        ctx.beginPath();
        ctx.moveTo(p0.x, p0.y);
        ctx.lineTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.lineTo(p3.x, p3.y);
        ctx.closePath();
        ctx.fillStyle = `rgb(${er},${eg},${eb})`;
        ctx.fill();
        ctx.strokeStyle = 'rgba(8,18,28,0.06)';
        ctx.lineWidth = 0.25;
        ctx.stroke();
      }

      ctx.restore();
    };

    const texSrc = overlay.textureUrl || null;
    const start = () => {
      if (!texSrc || texMix <= 0) {
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
  }, [map, overlay, enabled, zIndex]);

  return null;
}
