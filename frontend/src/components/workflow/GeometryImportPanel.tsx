import { useRef, useState } from 'react';
import { Loader2, Upload } from 'lucide-react';

interface Props {
  loading?: boolean;
  hasMask: boolean;
  hasScene: boolean;
  maskLabel?: string | null;
  extractLoading?: boolean;
  onImportFile: (file: File) => Promise<void> | void;
  onExtractByMask: () => void;
  onClearMask: () => void;
}

const ACCEPT = '.zip,.shp,.kml,.kmz,.geojson,.json';

export function GeometryImportPanel({
  loading,
  hasMask,
  hasScene,
  maskLabel,
  extractLoading,
  onImportFile,
  onExtractByMask,
  onClearMask,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const onPick = async (file: File | null) => {
    setLocalError(null);
    if (!file) return;
    try {
      await onImportFile(file);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : 'Import failed');
    }
  };

  return (
    <div className="mb-3 space-y-2 rounded-xl border border-[var(--accent)]/50 bg-[var(--accent-soft)]/30 p-3">
      <div className="flex items-center gap-2 text-xs font-semibold text-[var(--accent)]">
        <Upload className="h-4 w-4" />
        Vector mask upload
      </div>
      <p className="text-[11px] text-[var(--muted)]">
        Upload a <strong>shapefile (.zip)</strong>, <strong>KML</strong>, <strong>KMZ</strong>, or{' '}
        <strong>GeoJSON</strong> to set the AOI / extract mask.
      </p>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0] ?? null;
          e.target.value = '';
          void onPick(f);
        }}
      />
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={loading}
          className="ev-btn bg-[var(--accent)] text-white disabled:opacity-50"
          onClick={() => inputRef.current?.click()}
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Upload shapefile / KML / KMZ
        </button>
        {hasMask && (
          <button type="button" className="ev-btn-ghost text-[11px]" onClick={onClearMask}>
            Clear mask
          </button>
        )}
      </div>
      {maskLabel && (
        <div className="rounded border border-[var(--line)] bg-white px-2 py-1 text-[10px] text-[var(--ink)]">
          Mask: <span className="font-semibold">{maskLabel}</span>
        </div>
      )}
      {localError && (
        <div className="rounded border border-red-200 bg-red-50 px-2 py-1 text-[10px] text-red-700">
          {localError}
        </div>
      )}
      <button
        type="button"
        disabled={!hasMask || !hasScene || extractLoading || loading}
        className="ev-btn w-full border border-[var(--accent)] bg-white text-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50"
        title={
          !hasScene
            ? 'Eye-On a satellite image first'
            : !hasMask
              ? 'Upload or draw a polygon mask first'
              : 'Clip the Eye-On image to the mask'
        }
        onClick={onExtractByMask}
      >
        {extractLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
        Extract by mask
      </button>
      <p className="text-[10px] text-[var(--muted)]">
        Requires an Eye-On scene and a polygon mask (upload or AOI draw).
      </p>
    </div>
  );
}
