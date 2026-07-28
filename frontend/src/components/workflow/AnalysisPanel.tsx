import { Download, FileDown, GitCompare, X } from 'lucide-react';
import type { SceneSummary } from '../../services/catalogService';
import type { IndexName, IndexResult, ChangeResult } from '../../services/analyticsService';
import { analyticsService } from '../../services/analyticsService';

const INDICES: Array<{ id: IndexName; label: string; blurb: string }> = [
  { id: 'NDVI', label: 'NDVI', blurb: 'Vegetation' },
  { id: 'NDWI', label: 'NDWI', blurb: 'Water' },
  { id: 'NDBI', label: 'NDBI', blurb: 'Built-up' },
  { id: 'SAVI', label: 'SAVI', blurb: 'Soil-adj. veg.' },
  { id: 'BSI', label: 'BSI', blurb: 'Bare soil' },
  { id: 'LST', label: 'LST', blurb: 'Temperature' },
];

interface Props {
  focusScene: SceneSummary;
  scenes: SceneSummary[];
  visibleSceneIds: string[];
  selectedIndex: IndexName | null;
  result: IndexResult | null;
  changeResult: ChangeResult | null;
  compareSceneId: string | null;
  loading: boolean;
  onClose: () => void;
  onPickIndex: (index: IndexName) => void;
  onCompareSceneId: (id: string | null) => void;
  onRunChange: () => void;
  onDownloadScene: () => void;
}

export function AnalysisPanel({
  focusScene,
  scenes,
  visibleSceneIds,
  selectedIndex,
  result,
  changeResult,
  compareSceneId,
  loading,
  onClose,
  onPickIndex,
  onCompareSceneId,
  onRunChange,
  onDownloadScene,
}: Props) {
  const compareCandidates = scenes.filter(
    (s) => s.id !== focusScene.id && visibleSceneIds.includes(s.id),
  );
  // Also allow comparing with any listed scene
  const allOthers = scenes.filter((s) => s.id !== focusScene.id);

  return (
    <aside className="flex h-full min-h-0 w-full flex-col border-l border-[var(--line)] bg-white p-3 sm:p-4">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <h2 className="font-display text-lg font-semibold">Indices</h2>
          <p className="mt-0.5 line-clamp-2 text-xs text-[var(--muted)]">{focusScene.name}</p>
        </div>
        <button type="button" className="ev-btn-ghost p-1" onClick={onClose} title="Close">
          <X className="h-4 w-4" />
        </button>
      </div>

      <button type="button" className="ev-btn-primary mb-3 w-full text-xs" onClick={onDownloadScene}>
        <Download className="h-3.5 w-3.5" /> Download scene image
      </button>

      <p className="text-xs text-[var(--muted)]">Compute an index — result overlays on the map:</p>
      <div className="mt-2 grid grid-cols-2 gap-2">
        {INDICES.map((idx) => {
          const active = selectedIndex === idx.id && !changeResult;
          return (
            <button
              key={idx.id}
              type="button"
              disabled={loading}
              onClick={() => onPickIndex(idx.id)}
              className={`rounded-xl border px-3 py-2.5 text-left ${
                active
                  ? 'border-[var(--accent)] bg-[var(--accent)] text-white'
                  : 'border-[var(--line)] hover:border-[var(--accent)]'
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

      {loading && <p className="mt-3 text-sm text-[var(--muted)]">Computing…</p>}

      {result && !loading && (
        <div className="mt-3 space-y-2 overflow-y-auto">
          {result.formula && (
            <p className="rounded-lg bg-[var(--accent-soft)] px-2 py-1.5 font-mono text-[10px] text-[var(--accent)]">
              {result.formula}
            </p>
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
                <div className="text-[10px] uppercase text-[var(--muted)]">{label}</div>
                <div className="font-mono text-sm font-semibold text-[var(--accent)]">
                  {typeof value === 'number' && label !== 'Pixels' ? value.toFixed(3) : value}
                </div>
              </div>
            ))}
          </div>
          <button
            type="button"
            className="ev-btn-ghost w-full border border-[var(--line)] text-xs"
            onClick={() => {
              if (!result.overlay_base64) return;
              const a = document.createElement('a');
              a.href = analyticsService.toDataUrl(result.overlay_base64);
              a.download = `${result.index}_${focusScene.id}.png`;
              a.click();
            }}
          >
            <FileDown className="h-3.5 w-3.5" /> Export index PNG
          </button>
        </div>
      )}

      <div className="mt-4 border-t border-[var(--line)] pt-3">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
          <GitCompare className="h-4 w-4 text-[var(--accent)]" />
          Change detection
        </div>
        <p className="mb-2 text-xs text-[var(--muted)]">
          Tip: turn on two scenes with the eye, then compare them.
        </p>
        <select
          className="ev-input mb-2 text-xs"
          value={compareSceneId ?? ''}
          onChange={(e) => onCompareSceneId(e.target.value || null)}
        >
          <option value="">Select second scene…</option>
          {(compareCandidates.length ? compareCandidates : allOthers).map((s) => (
            <option key={s.id} value={s.id}>
              {s.collection} ·{' '}
              {s.sensing_time ? new Date(s.sensing_time).toLocaleDateString() : s.name.slice(0, 24)}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="ev-btn-primary w-full text-xs"
          disabled={!compareSceneId || loading}
          onClick={onRunChange}
        >
          Run change detection ({selectedIndex || 'NDVI'})
        </button>
        {changeResult && (
          <div className="mt-2 rounded-lg bg-[var(--accent-soft)] p-2 text-xs text-[var(--accent)]">
            <div>Δ mean: {changeResult.mean_difference.toFixed(4)}</div>
            <div>Changed: {(changeResult.change_ratio * 100).toFixed(1)}%</div>
            <button
              type="button"
              className="ev-btn-ghost mt-2 w-full border border-[var(--line)] text-xs"
              onClick={() => {
                const href = analyticsService.resolveOverlayUrl(changeResult);
                if (!href) return;
                const a = document.createElement('a');
                a.href = href;
                a.download = `change_${changeResult.index}.png`;
                a.click();
              }}
            >
              <FileDown className="h-3.5 w-3.5" /> Export change PNG
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
