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
import type { IndexName, IndexResult, ColormapInfo, ColormapName } from '../../services/analyticsService';
import { analyticsService } from '../../services/analyticsService';
import type {
  ClassCount,
  ClassStyle,
  ClassificationResult,
} from '../../services/classificationService';
import {
  DEFAULT_CLASS_STYLES,
  stylesForCount,
} from '../../services/classificationService';

const INDEX_LIST: Array<{ id: IndexName; label: string; defaultRamp: ColormapName }> = [
  { id: 'NDVI', label: 'NDVI', defaultRamp: 'rdylgn' },
  { id: 'NDWI', label: 'NDWI', defaultRamp: 'blues' },
  { id: 'NDBI', label: 'NDBI', defaultRamp: 'ylorbr' },
  { id: 'SAVI', label: 'SAVI', defaultRamp: 'rdylgn' },
  { id: 'BSI', label: 'BSI', defaultRamp: 'soil' },
  { id: 'EVI', label: 'EVI', defaultRamp: 'rdylgn' },
  { id: 'NDMI', label: 'NDMI', defaultRamp: 'brbg' },
  { id: 'NBR', label: 'Burn Index (NBR)', defaultRamp: 'rdbu' },
  { id: 'LST', label: 'LST', defaultRamp: 'thermal' },
];

interface Props {
  hasScene: boolean;
  loading: boolean;
  activeToolId: string | null;
  indexResult: IndexResult | null;
  compositeResult: CompositeResult | null;
  stretchResult: StretchResult | null;
  classificationResult?: ClassificationResult | null;
  stretchParams: { p_low: number; p_high: number; gamma: number; brightness: number; contrast: number };
  colormap?: ColormapName | string | null;
  onComposite: (preset: CompositePreset) => void;
  onIndex: (index: IndexName) => void;
  onClassify?: (opts: { n_classes: ClassCount; class_styles: ClassStyle[] }) => void;
  /** Apply new colors to an existing classification (no re-run). */
  onRecolorClassify?: (styles: ClassStyle[]) => void;
  onColormapChange?: (cmap: ColormapName) => void;
  onStretch: () => void;
  onStretchParams: (patch: Partial<Props['stretchParams']>) => void;
  onEnhance: (op: 'brightness' | 'contrast' | 'gamma' | 'sharpen' | 'denoise') => void;
  onExportIndexPng: () => void;
  onExportIndexCsv: () => void;
  onExportCompositePng: () => void;
  onExportStretchPng: () => void;
  onExportOverlayPng: () => void;
  onExportIndexGeotiff?: () => void;
  onExportCompositeGeotiff?: () => void;
  onExportStretchGeotiff?: () => void;
  onExportOverlayGeotiff?: () => void;
  onExportClassifyPng?: () => void;
  onExportClassifyCsv?: () => void;
  onExportClassifyGeotiff?: () => void;
  geotiffBusy?: boolean;
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
  classificationResult = null,
  stretchParams,
  colormap = null,
  onComposite,
  onIndex,
  onClassify,
  onRecolorClassify,
  onColormapChange,
  onStretch,
  onStretchParams,
  onEnhance,
  onExportIndexPng,
  onExportIndexCsv,
  onExportCompositePng,
  onExportStretchPng,
  onExportOverlayPng,
  onExportIndexGeotiff,
  onExportCompositeGeotiff,
  onExportStretchGeotiff,
  onExportOverlayGeotiff,
  onExportClassifyPng,
  onExportClassifyCsv,
  onExportClassifyGeotiff,
  geotiffBusy = false,
}: Props) {
  const [presets, setPresets] = useState<CompositePresetInfo[]>([]);
  const [thematic, setThematic] = useState<IndexThematicInfo[]>([]);
  const [ramps, setRamps] = useState<ColormapInfo[]>([]);
  const [nClasses, setNClasses] = useState<ClassCount>(6);
  const [allStyles, setAllStyles] = useState<ClassStyle[]>(DEFAULT_CLASS_STYLES);

  const activeStyles = useMemo(
    () => stylesForCount(nClasses, allStyles),
    [nClasses, allStyles],
  );

  useEffect(() => {
    void compositeService.listPresets().then(setPresets).catch(() => setPresets([]));
    void compositeService.listIndexThematic().then(setThematic).catch(() => setThematic([]));
    void analyticsService.listColormaps().then(setRamps).catch(() => setRamps([]));
  }, []);

  const updateStyle = (name: string, patch: Partial<ClassStyle>) => {
    setAllStyles((prev) =>
      prev.map((s) => (s.name === name ? { ...s, ...patch } : s)),
    );
  };

  const activeThematic = thematic.find((t) => t.id === indexResult?.index);
  const activeIndexMeta = INDEX_LIST.find((i) => i.id === indexResult?.index);
  const selectedRamp =
    (colormap as ColormapName | null) ||
    (indexResult?.colormap as ColormapName | undefined) ||
    activeIndexMeta?.defaultRamp ||
    'rdylgn';
  const selectedRampInfo = ramps.find((r) => r.id === selectedRamp);
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

      {/* Unsupervised classification */}
      <section>
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
          Unsupervised classification
        </h3>
        <p className="mb-1.5 text-[10px] text-[var(--muted)]">
          Choose <strong>3–8</strong> classes, optionally set colors, then run. After
          classification you can change colors anytime without re-running.
        </p>

        <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
          Number of classes
        </label>
        <div className="mb-2 grid grid-cols-6 gap-1">
          {([3, 4, 5, 6, 7, 8] as ClassCount[]).map((n) => (
            <button
              key={n}
              type="button"
              disabled={loading}
              onClick={() => setNClasses(n)}
              className={`rounded border px-1 py-1.5 text-[11px] font-semibold ${
                nClasses === n
                  ? 'border-[var(--accent)] bg-[var(--accent)] text-white'
                  : 'border-[var(--line)] bg-white hover:border-[var(--accent)]'
              }`}
            >
              {n}
            </button>
          ))}
        </div>

        <div className="mb-1 flex items-center justify-between">
          <label className="text-[10px] font-medium text-[var(--muted)]">
            Colors before run
          </label>
          <button
            type="button"
            className="text-[10px] text-[var(--accent)] underline-offset-2 hover:underline"
            onClick={() => setAllStyles(DEFAULT_CLASS_STYLES.map((s) => ({ ...s })))}
          >
            Reset defaults
          </button>
        </div>
        <div className="mb-2 space-y-1 rounded border border-[var(--line)] bg-white p-1.5">
          {activeStyles.map((s) => (
            <div
              key={s.name}
              className="flex items-center gap-2 rounded px-1 py-0.5 hover:bg-[var(--surface-2,#f8fafc)]"
            >
              <input
                type="color"
                value={s.color}
                aria-label={`Color for ${s.label}`}
                className="h-7 w-8 cursor-pointer rounded border border-[var(--line)] bg-transparent p-0"
                onChange={(e) => updateStyle(s.name, { color: e.target.value.toUpperCase() })}
              />
              <input
                type="text"
                value={s.color}
                spellCheck={false}
                className="w-[72px] rounded border border-[var(--line)] px-1 py-0.5 font-mono text-[10px]"
                onChange={(e) => {
                  const v = e.target.value.trim();
                  if (/^#?[0-9a-fA-F]{6}$/.test(v)) {
                    updateStyle(s.name, {
                      color: (v.startsWith('#') ? v : `#${v}`).toUpperCase(),
                    });
                  }
                }}
              />
              <input
                type="text"
                value={s.label}
                className="min-w-0 flex-1 rounded border border-[var(--line)] px-1.5 py-0.5 text-[11px]"
                onChange={(e) => updateStyle(s.name, { label: e.target.value })}
                aria-label={`Label for ${s.name}`}
              />
            </div>
          ))}
        </div>

        <button
          type="button"
          disabled={loading || !onClassify}
          onClick={() =>
            onClassify?.({ n_classes: nClasses, class_styles: activeStyles })
          }
          className={`w-full rounded-lg border px-2 py-2 text-left text-[11px] font-semibold ${
            activeToolId === 'unsupervised_classify' || classificationResult
              ? 'border-[var(--accent)] bg-[var(--accent)] text-white'
              : 'border-[var(--line)] bg-white hover:border-[var(--accent)]'
          }`}
        >
          Run {nClasses}-class unsupervised classify
        </button>
        {classificationResult && (
          <div className="mt-2 space-y-2 rounded border border-[var(--line)] bg-white p-2">
            <div className="text-[10px] text-[var(--muted)]">
              {classificationResult.message}
              {classificationResult.agreement_percent != null
                ? ` · member agreement ${classificationResult.agreement_percent}%`
                : ''}
            </div>

            <div className="rounded border border-dashed border-[var(--line)] bg-[var(--surface-2,#f8fafc)] p-1.5">
              <div className="mb-1 text-[10px] font-semibold text-[var(--ink,#0f172a)]">
                Change colors after classification
              </div>
              <p className="mb-1.5 text-[9px] text-[var(--muted)]">
                Pick new colors below — the map updates immediately (no re-classify).
              </p>
              <div className="space-y-1">
                {classificationResult.classes.map((c) => (
                  <div key={c.class_id} className="flex items-center gap-2">
                    <input
                      type="color"
                      value={c.color}
                      aria-label={`Recolor ${c.label}`}
                      className="h-7 w-8 cursor-pointer rounded border border-[var(--line)] bg-transparent p-0"
                      disabled={!classificationResult.class_map_base64 || !onRecolorClassify}
                      onChange={(e) => {
                        const color = e.target.value.toUpperCase();
                        const next = classificationResult.classes.map((row) =>
                          row.class_id === c.class_id
                            ? {
                                name: row.name,
                                label: row.label,
                                color,
                                class_id: row.class_id,
                              }
                            : {
                                name: row.name,
                                label: row.label,
                                color: row.color,
                                class_id: row.class_id,
                              },
                        );
                        onRecolorClassify?.(next);
                      }}
                    />
                    <span
                      className="inline-block h-3 w-3 rounded-sm border border-black/10"
                      style={{ background: c.color }}
                    />
                    <span className="min-w-0 flex-1 text-[11px]">{c.label}</span>
                    <span className="font-mono text-[9px] text-[var(--muted)]">
                      {c.color}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <table className="w-full text-left text-[10px]">
              <thead>
                <tr className="text-[var(--muted)]">
                  <th className="py-0.5 font-medium">Class</th>
                  <th className="py-0.5 font-medium">%</th>
                  <th className="py-0.5 font-medium">Area (km²)</th>
                </tr>
              </thead>
              <tbody>
                {classificationResult.classes.map((c) => (
                  <tr key={c.class_id} className="border-t border-[var(--line)]">
                    <td className="py-0.5">
                      <span className="inline-flex items-center gap-1">
                        <span
                          className="inline-block h-2 w-2 rounded-sm border border-black/10"
                          style={{ background: c.color }}
                        />
                        {c.label}
                      </span>
                    </td>
                    <td className="py-0.5">{c.percent.toFixed(1)}</td>
                    <td className="py-0.5 font-medium">{c.area_km2.toFixed(3)}</td>
                  </tr>
                ))}
                <tr className="border-t border-[var(--line)] font-semibold">
                  <td className="py-0.5">Total</td>
                  <td className="py-0.5">100</td>
                  <td className="py-0.5">
                    {classificationResult.total_area_km2.toFixed(3)}
                  </td>
                </tr>
              </tbody>
            </table>
            <div className="grid grid-cols-3 gap-1">
              <button
                type="button"
                className="ev-btn-ghost justify-center px-1 py-1 text-[10px]"
                disabled={!classificationResult.overlay_base64}
                onClick={() => onExportClassifyPng?.()}
              >
                <Download className="h-3 w-3" /> Map PNG
              </button>
              <button
                type="button"
                className="ev-btn-ghost justify-center px-1 py-1 text-[10px]"
                onClick={() => onExportClassifyCsv?.()}
              >
                <Download className="h-3 w-3" /> Areas CSV
              </button>
              <button
                type="button"
                className="ev-btn-ghost justify-center px-1 py-1 text-[10px]"
                disabled={geotiffBusy}
                onClick={() => onExportClassifyGeotiff?.()}
              >
                <Download className="h-3 w-3" /> GeoTIFF
              </button>
            </div>
          </div>
        )}
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
        <div className="mt-2 space-y-1.5 rounded border border-[var(--line)] bg-white p-2 text-[10px]">
          <div className="font-semibold uppercase tracking-wide text-[var(--muted)]">
            Color ramp
          </div>
          <div className="grid grid-cols-1 gap-1">
            {(ramps.length
              ? ramps
              : INDEX_LIST.map((i) => ({
                  id: i.defaultRamp,
                  label: i.defaultRamp,
                  stops: [] as ColormapInfo['stops'],
                }))
            ).map((ramp) => {
              const on = selectedRamp === ramp.id;
              const grad =
                ramp.stops?.length > 0
                  ? ramp.stops.map((s) => s.color).join(', ')
                  : '#888, #ccc';
              return (
                <button
                  key={ramp.id}
                  type="button"
                  disabled={loading}
                  title={ramp.label}
                  onClick={() => onColormapChange?.(ramp.id as ColormapName)}
                  className={`flex items-center gap-2 rounded border px-2 py-1 text-left ${
                    on
                      ? 'border-[var(--accent)] bg-[var(--accent-soft)]'
                      : 'border-[var(--line)] hover:border-[var(--accent)]'
                  }`}
                >
                  <span
                    className="h-2.5 w-16 shrink-0 rounded-full border border-[var(--line)]"
                    style={{ background: `linear-gradient(90deg, ${grad})` }}
                  />
                  <span className="truncate font-medium">{ramp.label}</span>
                </button>
              );
            })}
          </div>
          {selectedRampInfo && (
            <div
              className="mt-1 h-2 w-full rounded"
              style={{
                background: `linear-gradient(90deg, ${selectedRampInfo.stops.map((s) => s.color).join(', ')})`,
              }}
            />
          )}
          <p className="text-[9px] text-[var(--muted)]">
            Pick a ramp, then click an index (or re-click the active one) to apply.
          </p>
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
              </>
            )}
            <div>
              <span className="font-semibold">Color ramp: </span>
              {selectedRampInfo?.label || selectedRamp}
            </div>
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
        <p className="mb-1 text-[10px] text-[var(--muted)]">
          After True Color / indices / stretch, download PNG or georeferenced{' '}
          <strong>GeoTIFF</strong>.
        </p>
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
            className="ev-btn border border-[var(--accent)] bg-[var(--accent-soft)] text-[10px] text-[var(--accent)]"
            disabled={!indexResult || geotiffBusy}
            onClick={() => onExportIndexGeotiff?.()}
          >
            {geotiffBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
            Index GeoTIFF
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
            className="ev-btn border border-[var(--accent)] bg-[var(--accent-soft)] text-[10px] text-[var(--accent)]"
            disabled={!compositeResult || geotiffBusy}
            onClick={() => onExportCompositeGeotiff?.()}
          >
            {geotiffBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
            Composite GeoTIFF
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
            className="ev-btn border border-[var(--accent)] bg-[var(--accent-soft)] text-[10px] text-[var(--accent)]"
            disabled={!stretchResult || geotiffBusy}
            onClick={() => onExportStretchGeotiff?.()}
          >
            {geotiffBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
            Stretch GeoTIFF
          </button>
          <button
            type="button"
            className="ev-btn border border-[var(--line)] bg-white text-[10px]"
            onClick={onExportOverlayPng}
          >
            <Download className="h-3 w-3" /> Active overlay PNG
          </button>
          <button
            type="button"
            className="ev-btn border border-[var(--accent)] bg-[var(--accent-soft)] text-[10px] text-[var(--accent)]"
            disabled={geotiffBusy}
            onClick={() => onExportOverlayGeotiff?.()}
          >
            {geotiffBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
            Active overlay GeoTIFF
          </button>
        </div>
      </section>
    </div>
  );
}
