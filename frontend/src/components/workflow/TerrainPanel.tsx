import { useMemo, useRef, useEffect, useState } from 'react';
import {
  Mountain,
  Triangle,
  Compass,
  Sun,
  Waves,
  Droplets,
  Eye,
  LineChart,
  Binoculars,
  Loader2,
} from 'lucide-react';
import type { TerrainProduct, TerrainResult } from '../../services/terrainService';
import type { LegendInfo } from '../../services/analyticsService';

const PRODUCTS: Array<{
  id: TerrainProduct;
  label: string;
  icon: typeof Mountain;
  hint: string;
}> = [
  { id: 'dem', label: 'DEM 3D', icon: Mountain, hint: 'Elevation surface + 3D view' },
  { id: 'slope', label: 'Slope', icon: Triangle, hint: 'Slope degrees with legend' },
  { id: 'aspect', label: 'Aspect', icon: Compass, hint: 'Aspect degrees with legend' },
  { id: 'hillshade', label: 'Hillshade', icon: Sun, hint: 'Shaded relief with legend' },
  { id: 'contour', label: 'Contours', icon: Waves, hint: 'Contour generation' },
  { id: 'watershed', label: 'Watershed', icon: Droplets, hint: 'Drainage + catchments' },
  { id: 'viewshed', label: 'Viewshed', icon: Eye, hint: 'On-the-fly visibility' },
  { id: 'profile', label: '3D Profile', icon: LineChart, hint: 'Elevation along line' },
  { id: 'line_of_sight', label: 'Line of sight', icon: Binoculars, hint: 'Observer → target' },
];

interface Props {
  loading: boolean;
  result: TerrainResult | null;
  contourInterval: number;
  observerHeight: number;
  onContourInterval: (v: number) => void;
  onObserverHeight: (v: number) => void;
  onRun: (product: TerrainProduct) => void;
  onClose3d?: () => void;
}

function DemCanvas({ grid }: { grid: number[][] }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [angle, setAngle] = useState(0.55);
  const [tilt, setTilt] = useState(0.9);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !grid.length) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#0b1a16';
    ctx.fillRect(0, 0, W, H);

    const rows = grid.length;
    const cols = grid[0].length;
    let zmin = Infinity;
    let zmax = -Infinity;
    for (const row of grid) {
      for (const z of row) {
        if (z < zmin) zmin = z;
        if (z > zmax) zmax = z;
      }
    }
    const span = zmax - zmin || 1;
    const cx = W / 2;
    const cy = H * 0.62;
    const scale = Math.min(W, H) / (Math.max(rows, cols) * 1.35);

    const project = (i: number, j: number, z: number) => {
      const x = (j - cols / 2) * scale;
      const y = (i - rows / 2) * scale;
      const h = ((z - zmin) / span) * scale * 2.2;
      const xr = x * Math.cos(angle) - y * Math.sin(angle);
      const yr = x * Math.sin(angle) + y * Math.cos(angle);
      return [cx + xr, cy + yr * tilt - h] as const;
    };

    for (let i = 0; i < rows - 1; i++) {
      for (let j = 0; j < cols - 1; j++) {
        const z = grid[i][j];
        const t = (z - zmin) / span;
        const [x0, y0] = project(i, j, grid[i][j]);
        const [x1, y1] = project(i, j + 1, grid[i][j + 1]);
        const [x2, y2] = project(i + 1, j + 1, grid[i + 1][j + 1]);
        const [x3, y3] = project(i + 1, j, grid[i + 1][j]);
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.lineTo(x3, y3);
        ctx.closePath();
        const r = Math.floor(40 + 140 * t);
        const g = Math.floor(90 + 80 * (1 - Math.abs(t - 0.4)));
        const b = Math.floor(70 + 40 * (1 - t));
        ctx.fillStyle = `rgb(${r},${g},${b})`;
        ctx.fill();
        ctx.strokeStyle = 'rgba(15,42,34,0.25)';
        ctx.lineWidth = 0.4;
        ctx.stroke();
      }
    }
  }, [grid, angle, tilt]);

  return (
    <div className="space-y-2">
      <canvas ref={ref} width={360} height={220} className="w-full rounded-lg border border-[var(--line)]" />
      <div className="grid grid-cols-2 gap-2 text-[10px] text-[var(--muted)]">
        <label className="flex items-center gap-2">
          Rotate
          <input
            type="range"
            min={0}
            max={628}
            value={Math.round(angle * 100)}
            onChange={(e) => setAngle(Number(e.target.value) / 100)}
            className="w-full accent-[var(--accent)]"
          />
        </label>
        <label className="flex items-center gap-2">
          Tilt
          <input
            type="range"
            min={40}
            max={140}
            value={Math.round(tilt * 100)}
            onChange={(e) => setTilt(Number(e.target.value) / 100)}
            className="w-full accent-[var(--accent)]"
          />
        </label>
      </div>
    </div>
  );
}

function ProfileChart({ profile }: { profile: Array<Record<string, number>> }) {
  const path = useMemo(() => {
    if (!profile.length) return '';
    const w = 320;
    const h = 120;
    const xs = profile.map((p) => p.distance_m);
    const ys = profile.map((p) => p.elevation_m);
    const xmin = Math.min(...xs);
    const xmax = Math.max(...xs) || 1;
    const ymin = Math.min(...ys);
    const ymax = Math.max(...ys) || 1;
    return profile
      .map((p, i) => {
        const x = ((p.distance_m - xmin) / (xmax - xmin || 1)) * (w - 16) + 8;
        const y = h - 8 - ((p.elevation_m - ymin) / (ymax - ymin || 1)) * (h - 16);
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  }, [profile]);

  return (
    <svg viewBox="0 0 320 120" className="w-full rounded-lg border border-[var(--line)] bg-white">
      <path d={path} fill="none" stroke="#1f6f54" strokeWidth="2" />
    </svg>
  );
}

export function TerrainPanel({
  loading,
  result,
  contourInterval,
  observerHeight,
  onContourInterval,
  onObserverHeight,
  onRun,
}: Props) {
  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3">
      <div>
        <h2 className="font-display text-sm font-semibold">Terrain & DEM</h2>
        <p className="text-[11px] text-[var(--muted)]">
          DEM visualization, slope/aspect/hillshade legends, contours, watershed, viewshed & LOS
        </p>
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        {PRODUCTS.map(({ id, label, icon: Icon, hint }) => (
          <button
            key={id}
            type="button"
            title={hint}
            disabled={loading}
            onClick={() => onRun(id)}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2 py-2 text-left text-[11px] font-medium ${
              result?.product === id
                ? 'border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]'
                : 'border-[var(--line)] hover:bg-[var(--accent-soft)]'
            }`}
          >
            <Icon className="h-3.5 w-3.5 shrink-0" />
            {label}
          </button>
        ))}
      </div>

      <div className="space-y-2 rounded-lg border border-[var(--line)] bg-white p-2 text-[11px]">
        <label className="flex items-center justify-between gap-2">
          Contour interval (m)
          <input
            type="number"
            min={5}
            max={200}
            value={contourInterval}
            onChange={(e) => onContourInterval(Number(e.target.value) || 25)}
            className="w-20 rounded border border-[var(--line)] px-2 py-1"
          />
        </label>
        <label className="flex items-center justify-between gap-2">
          Observer height (m)
          <input
            type="number"
            min={0}
            max={500}
            step={0.1}
            value={observerHeight}
            onChange={(e) => onObserverHeight(Number(e.target.value) || 1.7)}
            className="w-20 rounded border border-[var(--line)] px-2 py-1"
          />
        </label>
        <p className="text-[10px] text-[var(--muted)]">
          Viewshed uses map center (or place). Profile / LOS use the Distance line if drawn.
        </p>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
          <Loader2 className="h-4 w-4 animate-spin" /> Computing terrain…
        </div>
      )}

      {result && (
        <div className="space-y-2 rounded-lg border border-[var(--line)] bg-white p-2">
          <div className="text-xs font-semibold capitalize">{result.product.replaceAll('_', ' ')}</div>
          {result.message && (
            <div className="text-[11px] text-[var(--muted)]">{result.message}</div>
          )}
          {result.formula && (
            <div className="font-mono text-[10px] text-[var(--muted)]">{result.formula}</div>
          )}
          {result.dem_stats && (
            <div className="grid grid-cols-2 gap-1 text-[10px]">
              <span>Min {result.dem_stats.min?.toFixed(1)} m</span>
              <span>Max {result.dem_stats.max?.toFixed(1)} m</span>
              <span>Mean {result.dem_stats.mean?.toFixed(1)} m</span>
              <span>Std {result.dem_stats.std?.toFixed(1)} m</span>
            </div>
          )}
          {result.dem_grid && result.dem_grid.length > 0 && <DemCanvas grid={result.dem_grid} />}
          {result.profile && result.profile.length > 1 && <ProfileChart profile={result.profile} />}
          {result.line_of_sight && (
            <div
              className={`rounded px-2 py-1 text-xs font-semibold ${
                result.line_of_sight.visible
                  ? 'bg-teal-50 text-teal-800'
                  : 'bg-amber-50 text-amber-800'
              }`}
            >
              {result.line_of_sight.visible ? 'Line of sight: CLEAR' : 'Line of sight: BLOCKED'}
              <span className="ml-2 font-normal">
                min clearance {result.line_of_sight.min_clearance_m.toFixed(1)} m
              </span>
            </div>
          )}
          {result.legend && <MiniLegend legend={result.legend} />}
        </div>
      )}
    </div>
  );
}

function MiniLegend({ legend }: { legend: LegendInfo }) {
  return (
    <div className="space-y-1">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-[var(--muted)]">
        {legend.label}
      </div>
      <div
        className="h-2.5 rounded"
        style={{
          background: `linear-gradient(90deg, ${legend.stops.map((s) => s.color).join(', ')})`,
        }}
      />
      <div className="flex justify-between font-mono text-[10px] text-[var(--muted)]">
        <span>{legend.min.toFixed(1)}</span>
        <span>{legend.unit}</span>
        <span>{legend.max.toFixed(1)}</span>
      </div>
    </div>
  );
}
