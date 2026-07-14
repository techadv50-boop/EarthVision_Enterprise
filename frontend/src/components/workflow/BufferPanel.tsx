import { useState } from 'react';
import { CircleDot, Loader2 } from 'lucide-react';

interface Props {
  hasGeometry: boolean;
  geometryType?: string | null;
  loading?: boolean;
  lastDistance?: number | null;
  lastArea?: number | null;
  onApply: (distanceMeters: number) => void;
  onClear: () => void;
}

const PRESETS = [50, 100, 250, 500, 1000, 2000, 5000];

export function BufferPanel({
  hasGeometry,
  geometryType,
  loading,
  lastDistance,
  lastArea,
  onApply,
  onClear,
}: Props) {
  const [distance, setDistance] = useState(500);

  if (!hasGeometry) {
    return (
      <div className="rounded-xl border border-dashed border-[var(--line)] bg-white/80 p-3 text-[11px] text-[var(--muted)]">
        Draw a <strong>point</strong>, <strong>line</strong> (Distance tool), or{' '}
        <strong>polygon</strong> (AOI) — then Buffer appears here.
      </div>
    );
  }

  return (
    <div className="space-y-2 rounded-xl border border-[var(--accent)] bg-[var(--accent-soft)]/40 p-3 shadow-sm">
      <div className="flex items-center gap-2 text-xs font-semibold text-[var(--accent)]">
        <CircleDot className="h-4 w-4" />
        Buffer analysis
        {geometryType && (
          <span className="rounded bg-white/80 px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted)]">
            {geometryType}
          </span>
        )}
      </div>
      <p className="text-[11px] text-[var(--muted)]">
        Apply a distance buffer to the drawn feature on the imagery.
      </p>
      <label className="flex items-center justify-between gap-2 text-[11px]">
        Distance (m)
        <input
          type="number"
          min={1}
          max={100000}
          value={distance}
          onChange={(e) => setDistance(Math.max(1, Number(e.target.value) || 1))}
          className="w-24 rounded border border-[var(--line)] bg-white px-2 py-1"
        />
      </label>
      <div className="flex flex-wrap gap-1">
        {PRESETS.map((p) => (
          <button
            key={p}
            type="button"
            className="rounded-full border border-[var(--line)] bg-white px-2 py-0.5 text-[10px] hover:border-[var(--accent)]"
            onClick={() => setDistance(p)}
          >
            {p >= 1000 ? `${p / 1000} km` : `${p} m`}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={loading}
          onClick={() => onApply(distance)}
          className="ev-btn flex-1 bg-[var(--accent)] text-white"
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Apply buffer
        </button>
        <button type="button" className="ev-btn-ghost text-xs" onClick={onClear}>
          Clear
        </button>
      </div>
      {lastDistance != null && (
        <div className="text-[10px] text-[var(--muted)]">
          Last buffer {lastDistance} m
          {lastArea != null ? ` · area ${(lastArea / 1e6).toFixed(3)} km²` : ''}
        </div>
      )}
    </div>
  );
}
