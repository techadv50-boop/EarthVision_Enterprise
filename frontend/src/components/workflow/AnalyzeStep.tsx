import { ArrowLeft } from 'lucide-react';
import type { SceneSummary } from '../../services/catalogService';
import type { IndexName, IndexResult } from '../../services/analyticsService';

const INDICES: Array<{ id: IndexName; label: string; blurb: string }> = [
  { id: 'NDVI', label: 'NDVI', blurb: 'Vegetation' },
  { id: 'NDWI', label: 'NDWI', blurb: 'Water' },
  { id: 'NDBI', label: 'NDBI', blurb: 'Built-up' },
  { id: 'SAVI', label: 'SAVI', blurb: 'Soil-adj. veg.' },
  { id: 'BSI', label: 'BSI', blurb: 'Bare soil' },
  { id: 'LST', label: 'LST', blurb: 'Temperature' },
];

interface Props {
  scene: SceneSummary;
  selectedIndex: IndexName | null;
  result: IndexResult | null;
  loading: boolean;
  onPickIndex: (index: IndexName) => void;
  onBack: () => void;
}

export function AnalyzeStep({
  scene,
  selectedIndex,
  result,
  loading,
  onPickIndex,
  onBack,
}: Props) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <button type="button" className="ev-btn-ghost mb-1 -ml-2 w-fit px-2 py-1 text-xs" onClick={onBack}>
        <ArrowLeft className="h-3.5 w-3.5" /> Back to images
      </button>
      <h2 className="font-display text-lg font-semibold">Analyze image</h2>
      <p className="mt-1 line-clamp-2 text-xs text-[var(--muted)]">{scene.name}</p>
      <p className="mt-3 text-sm text-[var(--muted)]">Choose an index to compute:</p>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
        {INDICES.map((idx) => {
          const active = selectedIndex === idx.id;
          return (
            <button
              key={idx.id}
              type="button"
              disabled={loading}
              onClick={() => onPickIndex(idx.id)}
              className={`rounded-xl border px-3 py-3 text-left transition ${
                active
                  ? 'border-[var(--accent)] bg-[var(--accent)] text-white'
                  : 'border-[var(--line)] bg-white hover:border-[var(--accent)]'
              }`}
            >
              <div className="text-sm font-semibold">{idx.label}</div>
              <div className={`text-[11px] ${active ? 'text-white/80' : 'text-[var(--muted)]'}`}>
                {idx.blurb}
              </div>
            </button>
          );
        })}
      </div>

      {loading && <p className="mt-4 text-sm text-[var(--muted)]">Computing {selectedIndex}…</p>}

      {result && !loading && (
        <div className="mt-4 min-h-0 flex-1 space-y-3 overflow-y-auto">
          {result.preview_base64 && (
            <img
              src={`data:image/png;base64,${result.preview_base64}`}
              alt={`${result.index} preview`}
              className="w-full rounded-xl border border-[var(--line)]"
              loading="lazy"
            />
          )}
          <div className="grid grid-cols-3 gap-2">
            {(
              [
                ['Mean', result.mean],
                ['Min', result.min],
                ['Max', result.max],
                ['Median', result.median],
                ['Std', result.std],
                ['Pixels', result.valid_pixels],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="rounded-lg bg-[var(--accent-soft)] p-2 text-center">
                <div className="text-[10px] uppercase tracking-wide text-[var(--muted)]">{label}</div>
                <div className="font-mono text-sm font-semibold text-[var(--accent)]">
                  {typeof value === 'number' && label !== 'Pixels' ? value.toFixed(3) : value}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
