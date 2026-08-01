import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Download, Eye, EyeOff, Loader2, Satellite, X } from 'lucide-react';
import {
  catalogService,
  type DownloadBandInfo,
  type SceneSummary,
} from '../../services/catalogService';
import { getErrorMessage } from '../../services/api';

interface Props {
  placeName: string;
  scenes: SceneSummary[];
  visibleSceneIds: string[];
  focusSceneId: string | null;
  loading: boolean;
  loadingOverlayIds: string[];
  downloadingIds?: string[];
  getSceneBbox: (scene: SceneSummary) => number[];
  onToggleEye: (scene: SceneSummary) => void;
  onDownloadBands: (scene: SceneSummary, bands: string[]) => Promise<void>;
  onDownloadPng?: (scene: SceneSummary) => Promise<void>;
  onFocus: (scene: SceneSummary) => void;
  onBack: () => void;
}

function formatDate(value?: string | null): string {
  if (!value) return 'Unknown date';
  try {
    return new Date(value).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return value;
  }
}

export function ScenesStep({
  placeName,
  scenes,
  visibleSceneIds,
  focusSceneId,
  loading,
  loadingOverlayIds,
  downloadingIds = [],
  getSceneBbox,
  onToggleEye,
  onDownloadBands,
  onDownloadPng,
  onFocus,
  onBack,
}: Props) {
  const [pickerSceneId, setPickerSceneId] = useState<string | null>(null);
  const [bandOptions, setBandOptions] = useState<DownloadBandInfo[]>([]);
  const [selectedBands, setSelectedBands] = useState<string[]>([]);
  const [bandsLoading, setBandsLoading] = useState(false);
  const [bandsError, setBandsError] = useState<string | null>(null);
  const [bandsNote, setBandsNote] = useState<string | null>(null);
  const [pngBusy, setPngBusy] = useState(false);

  const closePicker = useCallback(() => {
    setPickerSceneId(null);
    setBandOptions([]);
    setSelectedBands([]);
    setBandsError(null);
    setBandsNote(null);
    setBandsLoading(false);
  }, []);

  const openPicker = useCallback(
    async (scene: SceneSummary) => {
      if (pickerSceneId === scene.id) {
        closePicker();
        return;
      }
      setPickerSceneId(scene.id);
      setBandOptions([]);
      setSelectedBands([]);
      setBandsError(null);
      setBandsNote(null);
      setBandsLoading(true);
      try {
        const result = await catalogService.listBands(scene, {
          bbox: getSceneBbox(scene),
        });
        setBandOptions(result.bands);
        setBandsNote(result.note ?? null);
        // Full COGs are large — default to one product band, not all
        setSelectedBands(
          result.default_bands?.length
            ? [...result.default_bands]
            : result.bands.slice(0, 1).map((b) => b.id),
        );
      } catch (err) {
        setBandsError(getErrorMessage(err));
      } finally {
        setBandsLoading(false);
      }
    },
    [pickerSceneId, closePicker, getSceneBbox],
  );

  useEffect(() => {
    if (pickerSceneId && !scenes.some((s) => s.id === pickerSceneId)) {
      closePicker();
    }
  }, [scenes, pickerSceneId, closePicker]);

  const toggleBand = (bandId: string) => {
    setSelectedBands((prev) =>
      prev.includes(bandId) ? prev.filter((id) => id !== bandId) : [...prev, bandId],
    );
  };

  const selectAll = () => setSelectedBands(bandOptions.map((b) => b.id));
  const selectDefaults = () => {
    const one =
      bandOptions.find((b) => b.id === 'red' || b.id === 'vv') ?? bandOptions[0];
    setSelectedBands(one ? [one.id] : []);
  };

  const handleExport = async (scene: SceneSummary) => {
    if (!selectedBands.length) return;
    await onDownloadBands(scene, selectedBands);
  };

  const handlePng = async (scene: SceneSummary) => {
    if (!onDownloadPng) return;
    setPngBusy(true);
    try {
      await onDownloadPng(scene);
    } finally {
      setPngBusy(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3">
        <button type="button" className="ev-btn-ghost mb-1 -ml-2 px-2 py-1 text-xs" onClick={onBack}>
          <ArrowLeft className="h-3.5 w-3.5" /> Change place
        </button>
        <h2 className="font-display text-lg font-semibold">Satellite images</h2>
        <p className="text-sm text-[var(--muted)]">
          Near <span className="font-medium text-[var(--ink)]">{placeName}</span>
          {' — '}eye shows imagery; download lets you pick product bands (.tif).
        </p>
      </div>

      {loading && (
        <div className="flex flex-1 items-center justify-center text-sm text-[var(--muted)]">
          Loading scenes…
        </div>
      )}

      {!loading && scenes.length === 0 && (
        <div className="rounded-lg bg-[var(--accent-soft)] p-4 text-sm text-[var(--accent)]">
          No scenes found. Try another place or AOI.
        </div>
      )}

      {!loading && scenes.length > 0 && (
        <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
          {scenes.map((scene, i) => {
            const visible = visibleSceneIds.includes(scene.id);
            const focused = focusSceneId === scene.id;
            const overlayLoading = loadingOverlayIds.includes(scene.id);
            const downloading = downloadingIds.includes(scene.id);
            const pickerOpen = pickerSceneId === scene.id;
            return (
              <li key={scene.id}>
                <div
                  className={`ev-card w-full p-2.5 ${
                    focused ? 'border-[var(--accent)] ring-1 ring-[var(--accent)]/30' : ''
                  } ${visible ? 'bg-[var(--accent-soft)]/40' : ''}`}
                >
                  <div className="flex items-start gap-2">
                    <div className="mt-0.5 flex shrink-0 flex-col gap-1">
                      <button
                        type="button"
                        className="flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--line)] bg-white text-[var(--accent)] hover:bg-[var(--accent-soft)]"
                        title={visible ? 'Hide on map' : 'Show on map'}
                        onClick={() => onToggleEye(scene)}
                        disabled={overlayLoading}
                      >
                        {overlayLoading ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : visible ? (
                          <Eye className="h-4 w-4" />
                        ) : (
                          <EyeOff className="h-4 w-4 text-[var(--muted)]" />
                        )}
                      </button>
                      <button
                        type="button"
                        className={`flex h-9 w-9 items-center justify-center rounded-lg border bg-white text-[var(--accent)] hover:bg-[var(--accent-soft)] disabled:opacity-50 ${
                          pickerOpen
                            ? 'border-[var(--accent)] ring-1 ring-[var(--accent)]/40'
                            : 'border-[var(--line)]'
                        }`}
                        title="Download bands as GeoTIFF"
                        onClick={() => void openPicker(scene)}
                        disabled={downloading}
                      >
                        {downloading ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Download className="h-4 w-4" />
                        )}
                      </button>
                    </div>

                    <button
                      type="button"
                      className="min-w-0 flex-1 text-left"
                      onClick={() => {
                        if (visible) onFocus(scene);
                        else onToggleEye(scene);
                      }}
                    >
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-[var(--accent)] px-1.5 py-0.5 text-[10px] font-semibold text-white">
                          #{i + 1}
                        </span>
                        <span className="text-xs font-semibold uppercase tracking-wide text-[var(--accent)]">
                          {scene.collection}
                        </span>
                        {visible && (
                          <span className="rounded bg-teal-600 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-white">
                            on map
                          </span>
                        )}
                      </div>
                      <div className="mt-1 flex items-start gap-1.5">
                        <Satellite className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--muted)]" />
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium">{scene.name}</div>
                          <div className="mt-0.5 text-xs text-[var(--muted)]">
                            {formatDate(scene.sensing_time)}
                            {scene.cloud_cover != null && ` · ${scene.cloud_cover}% cloud`}
                          </div>
                        </div>
                      </div>
                    </button>
                  </div>

                  {pickerOpen && (
                    <div className="mt-2.5 border-t border-[var(--line)] pt-2.5">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <div className="min-w-0">
                          <div className="text-xs font-semibold text-[var(--ink)]">
                            Full product bands (.tif)
                          </div>
                          <p className="mt-0.5 text-[10px] leading-snug text-[var(--muted)]">
                            {bandsNote ||
                              'Original COG files (~40–120 MB each), not preview windows.'}
                          </p>
                        </div>
                        <button
                          type="button"
                          className="rounded p-0.5 text-[var(--muted)] hover:bg-[var(--accent-soft)] hover:text-[var(--accent)]"
                          title="Close"
                          onClick={closePicker}
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>

                      {bandsLoading && (
                        <div className="flex items-center gap-2 py-3 text-xs text-[var(--muted)]">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          Loading available bands…
                        </div>
                      )}

                      {bandsError && (
                        <div className="mb-2 rounded-md border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-700">
                          {bandsError}
                        </div>
                      )}

                      {!bandsLoading && !bandsError && bandOptions.length === 0 && (
                        <p className="py-2 text-xs text-[var(--muted)]">
                          No downloadable bands found for this scene.
                        </p>
                      )}

                      {!bandsLoading && bandOptions.length > 0 && (
                        <>
                          <div className="mb-1.5 flex flex-wrap gap-2 text-[10px]">
                            <button
                              type="button"
                              className="text-[var(--accent)] underline-offset-2 hover:underline"
                              onClick={selectAll}
                            >
                              Select all
                            </button>
                            <button
                              type="button"
                              className="text-[var(--accent)] underline-offset-2 hover:underline"
                              onClick={selectDefaults}
                            >
                              Default band
                            </button>
                            <button
                              type="button"
                              className="text-[var(--muted)] underline-offset-2 hover:underline"
                              onClick={() => setSelectedBands([])}
                            >
                              Clear
                            </button>
                          </div>
                          <ul className="mb-2 max-h-40 space-y-1 overflow-y-auto pr-0.5">
                            {bandOptions.map((band) => {
                              const checked = selectedBands.includes(band.id);
                              const fileName = band.filename || `${band.code || band.id}.tif`;
                              const format = band.format || 'GeoTIFF';
                              return (
                                <li key={band.id}>
                                  <label className="flex cursor-pointer items-start gap-2 rounded-md px-1.5 py-1 hover:bg-[var(--accent-soft)]/50">
                                    <input
                                      type="checkbox"
                                      className="mt-0.5 accent-[var(--accent)]"
                                      checked={checked}
                                      onChange={() => toggleBand(band.id)}
                                    />
                                    <span className="min-w-0">
                                      <span className="block font-mono text-xs font-semibold text-[var(--ink)]">
                                        {fileName}
                                        {band.size_label ? (
                                          <span className="ml-1.5 font-sans font-medium text-[var(--accent)]">
                                            {band.size_label}
                                          </span>
                                        ) : null}
                                      </span>
                                      <span className="block text-[10px] text-[var(--muted)]">
                                        {band.label}
                                        {' · '}
                                        {format}
                                        {band.extension ? ` ${band.extension}` : ''}
                                        {' · full resolution'}
                                      </span>
                                    </span>
                                  </label>
                                </li>
                              );
                            })}
                          </ul>
                          <div className="flex flex-col gap-1.5">
                            <button
                              type="button"
                              className="ev-btn-primary w-full justify-center text-xs"
                              disabled={downloading || selectedBands.length === 0}
                              onClick={() => void handleExport(scene)}
                            >
                              {downloading ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Download className="h-3.5 w-3.5" />
                              )}
                              {selectedBands.length > 1
                                ? `Download ZIP (${selectedBands.length} .tif)`
                                : selectedBands.length === 1
                                  ? `Download ${
                                      bandOptions.find((b) => b.id === selectedBands[0])
                                        ?.filename || '.tif'
                                    }`
                                  : 'Download .tif'}
                            </button>
                            {onDownloadPng && (
                              <button
                                type="button"
                                className="ev-btn-ghost w-full justify-center text-[11px]"
                                disabled={pngBusy || downloading}
                                onClick={() => void handlePng(scene)}
                              >
                                {pngBusy ? (
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                ) : null}
                                Preview PNG only
                              </button>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
