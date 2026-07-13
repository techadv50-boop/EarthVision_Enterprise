import { ArrowLeft, Download, GitCompare, FileDown } from 'lucide-react';
import type { SceneSummary } from '../../services/catalogService';
import type { IndexName, IndexResult, ChangeResult } from '../../services/analyticsService';
import { analyticsService } from '../../services/analyticsService';
import { authService } from '../../services/authService';

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
  scenes: SceneSummary[];
  selectedIndex: IndexName | null;
  result: IndexResult | null;
  changeResult: ChangeResult | null;
  compareScene: SceneSummary | null;
  loading: boolean;
  onPickIndex: (index: IndexName) => void;
  onCompareScene: (scene: SceneSummary | null) => void;
  onRunChange: () => void;
  onBack: () => void;
  onDownloadScene: () => void;
}

function authDownload(url: string, filename: string) {
  const token = localStorage.getItem('ev_access_token');
  fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
    .then((r) => r.blob())
    .then((blob) => {
      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(href);
    })
    .catch(() => {
      window.open(url, '_blank');
    });
}

export function AnalyzeStep({
  scene,
  scenes,
  selectedIndex,
  result,
  changeResult,
  compareScene,
  loading,
  onPickIndex,
  onCompareScene,
  onRunChange,
  onBack,
  onDownloadScene,
}: Props) {
  const others = scenes.filter((s) => s.id !== scene.id);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <button type="button" className="ev-btn-ghost mb-1 -ml-2 w-fit px-2 py-1 text-xs" onClick={onBack}>
        <ArrowLeft className="h-3.5 w-3.5" /> Back to images
      </button>
      <h2 className="font-display text-lg font-semibold">Analyze image</h2>
      <p className="mt-1 line-clamp-2 text-xs text-[var(--muted)]">{scene.name}</p>

      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className="ev-btn-primary text-xs" onClick={onDownloadScene}>
          <Download className="h-3.5 w-3.5" /> Download image
        </button>
      </div>

      <p className="mt-4 text-sm text-[var(--muted)]">Spectral indices (standard formulas):</p>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
        {INDICES.map((idx) => {
          const active = selectedIndex === idx.id && !changeResult;
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

      {loading && <p className="mt-3 text-sm text-[var(--muted)]">Computing…</p>}

      {result && !loading && (
        <div className="mt-3 space-y-2">
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
                <div className="text-[10px] uppercase tracking-wide text-[var(--muted)]">{label}</div>
                <div className="font-mono text-sm font-semibold text-[var(--accent)]">
                  {typeof value === 'number' && label !== 'Pixels' ? value.toFixed(3) : value}
                </div>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="ev-btn-ghost border border-[var(--line)] text-xs"
              onClick={() => {
                if (!result.overlay_base64) return;
                const a = document.createElement('a');
                a.href = analyticsService.toDataUrl(result.overlay_base64);
                a.download = `${result.index}_${scene.id}.png`;
                a.click();
              }}
            >
              <FileDown className="h-3.5 w-3.5" /> Export PNG
            </button>
            <button
              type="button"
              className="ev-btn-ghost border border-[var(--line)] text-xs"
              onClick={() => {
                void authService.isAuthenticated();
                authDownload(
                  analyticsService.exportIndexCsvUrl(result.index, scene.id),
                  `${result.index}_${scene.id}_stats.csv`,
                );
              }}
            >
              <FileDown className="h-3.5 w-3.5" /> Export CSV
            </button>
          </div>
        </div>
      )}

      <div className="mt-5 border-t border-[var(--line)] pt-3">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
          <GitCompare className="h-4 w-4 text-[var(--accent)]" />
          Change detection
        </div>
        <p className="mb-2 text-xs text-[var(--muted)]">
          Compare this scene with an earlier/later image. Difference is mapped on the globe.
        </p>
        <label className="mb-1 block text-[10px] uppercase tracking-wide text-[var(--muted)]">
          Compare with
        </label>
        <select
          className="ev-input mb-2 text-xs"
          value={compareScene?.id ?? ''}
          onChange={(e) => {
            const found = others.find((s) => s.id === e.target.value) ?? null;
            onCompareScene(found);
          }}
        >
          <option value="">Select second scene…</option>
          {others.map((s) => (
            <option key={s.id} value={s.id}>
              {s.collection} · {s.sensing_time ? new Date(s.sensing_time).toLocaleDateString() : s.name.slice(0, 28)}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="ev-btn-primary w-full text-xs"
          disabled={!compareScene || loading}
          onClick={onRunChange}
        >
          Run change detection ({selectedIndex || 'NDVI'})
        </button>
        {changeResult && (
          <div className="mt-2 rounded-lg bg-[var(--accent-soft)] p-2 text-xs text-[var(--accent)]">
            <div>Δ mean: {changeResult.mean_difference.toFixed(4)}</div>
            <div>Changed pixels: {(changeResult.change_ratio * 100).toFixed(1)}%</div>
            <div className="mt-1 font-mono text-[10px]">{changeResult.formula}</div>
            <button
              type="button"
              className="ev-btn-ghost mt-2 border border-[var(--line)] text-xs"
              onClick={() => {
                const a = document.createElement('a');
                a.href = analyticsService.toDataUrl(changeResult.overlay_base64);
                a.download = `change_${changeResult.index}.png`;
                a.click();
              }}
            >
              <FileDown className="h-3.5 w-3.5" /> Export change PNG
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
