import { useEffect, useMemo, useState } from 'react';
import { Download, Loader2 } from 'lucide-react';
import type {
  CompositePreset,
  CompositePresetInfo,
  CompositeResult,
  IndexThematicInfo,
  StretchResult,
} from '../../services/compositeService';
import { compositeService } from '../../services/compositeService';
import type { IndexName, IndexResult, LegendInfo } from '../../services/analyticsService';

const INDEX_LIST: Array<{ id: IndexName; label: string }> = [
  { id: 'NDVI', label: 'NDVI' },
  { id: 'NDWI', label: 'NDWI' },
  { id: 'NDBI', label: 'NDBI' },
  { id: 'SAVI', label: 'SAVI' },
  { id: 'BSI', label: 'BSI' },
  { id: 'EVI', label: 'EVI' },
  { id: 'NDMI', label: 'NDMI' },
  { id: 'NBR', label: 'Burn Index (NBR)' },
  { id: 'LST', label: 'LST' },
];

interface Props {
  hasScene: boolean;
  loading: boolean;
  activeToolId: string | null;
  indexResult: IndexResult | null;
  compositeResult: CompositeResult | null;
  stretchResult: StretchResult | null;
  stretchParams: { p_low: number; p_high: number; gamma: number; brightness: number; contrast: number };
  onComposite: (preset: CompositePreset) => void;
  onIndex: (index: IndexName) => void;
  onStretch: () => void;
  onStretchParams: (patch: Partial<Props['stretchParams']>) => void;
  onEnhance: (op: 'brightness' | 'contrast' | 'gamma' | 'sharpen' | 'denoise') => void;
  onExportIndexPng: () => void;
  onExportIndexCsv: () => void;
  onExportCompositePng: () => void;
  onExportStretchPng: () => void;
  onExportOverlayPng: () => void;
}

function HistogramChart({
  histogram,
}: {
  histogram: NonNullable<CompositeResult['histogram']> | IndexResult['histogram'] | null | undefined;
}) {
  const paths = useMemo(() => {
    if (!histogram) return null;
    // Index histogram: {counts, edges}
    if ('counts' in histogram && Array.isArray(histogram.counts)) {
      const counts = histogram.counts as number[];
      const max = Math.max(...counts, 1);
      const w = 280;
      const h = 80;
      const step = w / Math.max(counts.length - 1, 1);
      const d = counts
        .map((c, i) => {
          const x = i * step;
          const y = h - (c / max) * (h - 4);
          return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(' ');
      return { mono: d, rgb: null as null | Record<string, string> };
    }
    // RGB histogram
    const channels = (histogram as NonNullable<CompositeResult['histogram']>).channels;
    if (!channels) return null;
    const w = 280;
    const h = 80;
    const rgb: Record<string, string> = {};
    for (const [name, counts] of Object.entries(channels)) {
      const max = Math.max(...counts, 1);
      const step = w / Math.max(counts.length - 1, 1);
      rgb[name] = counts
        .map((c, i) => {
          const x = i * step;
          const y = h - (c / max) * (h - 4);
          return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(' ');
    }
    return { mono: null, rgb };
  }, [histogram]);

  if (!paths) {
    return (
      <div className="rounded border border-dashed border-[var(--line)] px-2 py-4 text-center text-[11px] text-[var(--muted)]">
        Run Histogram Stretch or an index to see the distribution
      </div>
    );
  }

  return (
    <svg viewBox="0 0 280 80" className="w-full rounded border border-[var(--line)] bg-white">
      {paths.mono && <path d={paths.mono} fill="none" stroke="#1f6f54" strokeWidth="1.5" />}
      {paths.rgb && (
        <>
          <path d={paths.rgb.red} fill="none" stroke="#dc2626" strokeWidth="1.2" opacity={0.85} />
          <path d={paths.rgb.green} fill="none" stroke="#16a34a" strokeWidth="1.2" opacity={0.85} />
          <path d={paths.rgb.blue} fill="none" stroke="#2563eb" strokeWidth="1.2" opacity={0.85} />
        </>
      )}
    </svg>
  );
}

export function ImageProcessingPanel({
  hasScene,
  loading,
  activeToolId,
  indexResult,
  compositeResult,
  stretchResult,
  stretchParams,
  onComposite,
  onIndex,
  onStretch,
  onStretchParams,
  onEnhance,
  onExportIndexPng,
  onExportIndexCsv,
  onExportCompositePng,
  onExportStretchPng,
  onExportOverlayPng,
}: Props) {
  const [presets, setPresets] = useState<CompositePresetInfo[]>([]);
  const [thematic, setThematic] = useState<IndexThematicInfo[]>([]);

  useEffect(() => {
    void compositeService.listPresets().then(setPresets).catch(() => setPresets([]));
    void compositeService.listIndexThematic().then(setThematic).catch(() => setThematic([]));
  }, []);

  const activeThematic = thematic.find((t) => t.id === indexResult?.index);
  const hist =
    stretchResult?.histogram ||
    compositeResult?.histogram ||
    indexResult?.histogram ||
    null;

  return (
    <div className="mb-3 space-y-3 rounded-lg border border-[var(--accent)]/40 bg-[var(--accent-soft)]/30 p-2">
      {!hasScene && (
        <p className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[10px] text-amber-800">
          Toggle a Sentinel-2 / Landsat scene eye for best results. Tools can still run on the AOI.
        </p>
      )}

      {/* Band combinations */}
      <section>
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
          Band combinations (RGB)
        </h3>
        <p className="mb-1 text-[10px] text-[var(--muted)]">
          False color infrared default: <strong>R=NIR, G=Red, B=Green</strong> (veg = red)
        </p>
        <div className="grid grid-cols-1 gap-1">
          {(presets.length
            ? presets
            : [
                {
                  id: 'true_color' as CompositePreset,
                  label: 'True Color',
                  formula: 'R=Red G=Green B=Blue',
                  use: '',
                  sentinel2: 'B04-B03-B02',
                  landsat: 'B4-B3-B2',
                  bands: { R: 'Red', G: 'Green', B: 'Blue' },
                },
                {
                  id: 'false_color_infrared' as CompositePreset,
                  label: 'False Color Infrared',
                  formula: 'R=NIR G=Red B=Green',
                  use: '',
                  sentinel2: 'B08-B04-B03',
                  landsat: 'B5-B4-B3',
                  bands: { R: 'NIR', G: 'Red', B: 'Green' },
                },
              ]
          ).map((p) => {
            const active = activeToolId === `composite-${p.id}` || compositeResult?.preset === p.id;
            return (
              <button
                key={p.id}
                type="button"
                disabled={loading}
                onClick={() => onComposite(p.id)}
                className={`rounded-lg border px-2 py-1.5 text-left text-[11px] ${
                  active
                    ? 'border-[var(--accent)] bg-[var(--accent)] text-white'
                    : 'border-[var(--line)] bg-white hover:border-[var(--accent)]'
                }`}
              >
                <div className="font-semibold">{p.label}</div>
                <div className={`font-mono text-[9px] ${active ? 'text-white/80' : 'text-[var(--muted)]'}`}>
                  {p.formula}
                </div>
                <div className={`text-[9px] ${active ? 'text-white/70' : 'text-[var(--muted)]'}`}>
                  S2 {p.sentinel2} · LS {p.landsat}
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* Spectral indices */}
      <section>
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
          Spectral indices (thematic)
        </h3>
        <div className="mt-1 grid grid-cols-3 gap-1">
          {INDEX_LIST.map((idx) => {
            const them = thematic.find((t) => t.id === idx.id);
            return (
              <button
                key={idx.id}
                type="button"
                title={them ? `${them.formula}\nBands: ${them.bands}` : idx.label}
                disabled={loading}
                onClick={() => onIndex(idx.id)}
                className={`rounded-lg border px-1.5 py-1.5 text-[11px] font-semibold ${
                  indexResult?.index === idx.id
                    ? 'border-[var(--accent)] bg-[var(--accent)] text-white'
                    : 'border-[var(--line)] bg-white hover:border-[var(--accent)]'
                }`}
              >
                {idx.label}
              </button>
            );
          })}
        </div>
        {(activeThematic || indexResult) && (
          <div className="mt-2 space-y-1 rounded border border-[var(--line)] bg-white p-2 text-[10px]">
            <div className="font-semibold">{indexResult?.index} formula</div>
            <div className="font-mono text-[var(--muted)]">
              {activeThematic?.formula || indexResult?.formula}
            </div>
            {activeThematic && (
              <>
                <div>
                  <span className="font-semibold">Bands: </span>
                  {activeThematic.bands}
                </div>
                <div>
                  <span className="font-semibold">Suggested RGB: </span>
                  {activeThematic.thematic_rgb}
                </div>
                <div>
                  <span className="font-semibold">Colormap: </span>
                  {activeThematic.colormap}
                </div>
              </>
            )}
            {indexResult && (
              <div className="grid grid-cols-2 gap-1 pt-1 font-mono text-[var(--muted)]">
                <span>mean {indexResult.mean.toFixed(3)}</span>
                <span>std {indexResult.std.toFixed(3)}</span>
                <span>min {indexResult.min.toFixed(3)}</span>
                <span>max {indexResult.max.toFixed(3)}</span>
              </div>
            )}
          </div>
        )}
      </section>

      {/* Histogram stretch */}
      <section>
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
          Histogram stretch
        </h3>
        <div className="mt-1 space-y-1.5 rounded border border-[var(--line)] bg-white p-2 text-[10px]">
          <label className="flex items-center justify-between gap-2">
            Low %
            <input
              type="number"
              min={0}
              max={40}
              value={stretchParams.p_low}
              onChange={(e) => onStretchParams({ p_low: Number(e.target.value) })}
              className="w-16 rounded border border-[var(--line)] px-1 py-0.5"
            />
          </label>
          <label className="flex items-center justify-between gap-2">
            High %
            <input
              type="number"
              min={60}
              max={100}
              value={stretchParams.p_high}
              onChange={(e) => onStretchParams({ p_high: Number(e.target.value) })}
              className="w-16 rounded border border-[var(--line)] px-1 py-0.5"
            />
          </label>
          <label className="flex items-center justify-between gap-2">
            Gamma
            <input
              type="number"
              min={0.3}
              max={3}
              step={0.1}
              value={stretchParams.gamma}
              onChange={(e) => onStretchParams({ gamma: Number(e.target.value) })}
              className="w-16 rounded border border-[var(--line)] px-1 py-0.5"
            />
          </label>
          <label className="flex items-center justify-between gap-2">
            Brightness
            <input
              type="range"
              min={50}
              max={180}
              value={Math.round(stretchParams.brightness * 100)}
              onChange={(e) => onStretchParams({ brightness: Number(e.target.value) / 100 })}
              className="w-full accent-[var(--accent)]"
            />
          </label>
          <label className="flex items-center justify-between gap-2">
            Contrast
            <input
              type="range"
              min={50}
              max={200}
              value={Math.round(stretchParams.contrast * 100)}
              onChange={(e) => onStretchParams({ contrast: Number(e.target.value) / 100 })}
              className="w-full accent-[var(--accent)]"
            />
          </label>
          <button
            type="button"
            disabled={loading}
            onClick={onStretch}
            className="ev-btn-primary w-full text-[11px]"
          >
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Apply histogram stretch
          </button>
          <div className="flex flex-wrap gap-1">
            {(['brightness', 'contrast', 'gamma', 'sharpen', 'denoise'] as const).map((op) => (
              <button
                key={op}
                type="button"
                className="rounded border border-[var(--line)] bg-[var(--bg)] px-2 py-0.5 text-[10px] capitalize hover:border-[var(--accent)]"
                onClick={() => onEnhance(op)}
              >
                {op}+
              </button>
            ))}
          </div>
          <HistogramChart histogram={hist} />
          {stretchResult?.message && (
            <div className="text-[var(--muted)]">{stretchResult.message}</div>
          )}
        </div>
      </section>

      {/* Exports */}
      <section>
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
          Export processed outcomes
        </h3>
        <div className="mt-1 grid grid-cols-2 gap-1">
          <button
            type="button"
            className="ev-btn border border-[var(--line)] bg-white text-[10px]"
            disabled={!indexResult?.overlay_base64}
            onClick={onExportIndexPng}
          >
            <Download className="h-3 w-3" /> Index PNG
          </button>
          <button
            type="button"
            className="ev-btn border border-[var(--line)] bg-white text-[10px]"
            disabled={!indexResult}
            onClick={onExportIndexCsv}
          >
            <Download className="h-3 w-3" /> Index CSV
          </button>
          <button
            type="button"
            className="ev-btn border border-[var(--line)] bg-white text-[10px]"
            disabled={!compositeResult?.overlay_base64}
            onClick={onExportCompositePng}
          >
            <Download className="h-3 w-3" /> Composite PNG
          </button>
          <button
            type="button"
            className="ev-btn border border-[var(--line)] bg-white text-[10px]"
            disabled={!stretchResult?.overlay_base64}
            onClick={onExportStretchPng}
          >
            <Download className="h-3 w-3" /> Stretch PNG
          </button>
          <button
            type="button"
            className="ev-btn col-span-2 border border-[var(--line)] bg-white text-[10px]"
            onClick={onExportOverlayPng}
          >
            <Download className="h-3 w-3" /> Download active map overlay PNG
          </button>
        </div>
      </section>
    </div>
  );
}

export type { LegendInfo };
