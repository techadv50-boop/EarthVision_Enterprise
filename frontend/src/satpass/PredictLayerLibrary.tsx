import { useEffect, useMemo, useState } from 'react';
import { Download, Loader2 } from 'lucide-react';
import { aoiLayerApi, type AoiLayerDetail, type AoiLayerSummary } from '@/services/api';

interface Props {
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
  onUseSelected: () => void;
  onClear: () => void;
  onExportAoi: () => void;
  exporting?: boolean;
  layerId: number | null;
  onLayerId: (id: number | null) => void;
  layerDetail: AoiLayerDetail | null;
  onLayerDetail: (detail: AoiLayerDetail | null) => void;
  layersEpoch?: number;
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  window.setTimeout(() => {
    a.remove();
    URL.revokeObjectURL(url);
  }, 1500);
}

export default function PredictLayerLibrary({
  selectedIds,
  onToggle,
  onUseSelected,
  onClear,
  onExportAoi,
  exporting,
  layerId,
  onLayerId,
  layerDetail,
  onLayerDetail,
  layersEpoch = 0,
}: Props) {
  const [layers, setLayers] = useState<AoiLayerSummary[]>([]);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const loadLayers = async () => {
    try {
      const { data } = await aoiLayerApi.list();
      setLayers(data);
      if (data.length && layerId == null) onLayerId(data[0].id);
    } catch {
      setError('Could not load district/city layers.');
    }
  };

  useEffect(() => {
    void loadLayers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layersEpoch]);

  useEffect(() => {
    if (layerId == null) {
      onLayerDetail(null);
      return;
    }
    let cancelled = false;
    setBusy('layer');
    aoiLayerApi
      .get(layerId)
      .then(({ data }) => {
        if (!cancelled) onLayerDetail(data);
      })
      .catch(() => {
        if (!cancelled) setError('Could not load that layer.');
      })
      .finally(() => {
        if (!cancelled) setBusy('');
      });
    return () => {
      cancelled = true;
    };
  }, [layerId, onLayerDetail]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = layerDetail?.features || [];
    if (!q) return rows;
    return rows.filter((f) => f.name.toLowerCase().includes(q));
  }, [layerDetail, query]);

  const downloadOriginal = async () => {
    if (layerId == null || !layerDetail) return;
    setBusy('dl');
    try {
      const { data } = await aoiLayerApi.download(layerId);
      saveBlob(data, layerDetail.original_filename || `${layerDetail.name}.zip`);
    } catch {
      setError('Could not download the shapefile zip.');
    } finally {
      setBusy('');
    }
  };

  return (
    <section>
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-cyan-400">
        District / city layers
      </h2>
      {layers.length === 0 ? (
        <p className="text-[11px] text-gray-500">
          No library shapefiles yet. An admin can add zipped district or city layers from the Layers
          button in the header.
        </p>
      ) : (
        <>
          <label className="block text-[11px] text-gray-400">
            Layer
            <select
              value={layerId ?? ''}
              onChange={(e) => onLayerId(e.target.value ? Number(e.target.value) : null)}
              className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10"
            >
              {layers.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name} ({l.feature_count})
                </option>
              ))}
            </select>
          </label>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter districts or cities"
            className="mt-2 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10 focus:ring-cyan-500"
          />
          <div className="mt-1 max-h-36 overflow-auto rounded bg-gray-900 text-[11px] ring-1 ring-white/10">
            {busy === 'layer' ? (
              <p className="px-2 py-2 text-gray-500">Loading…</p>
            ) : (
              filtered.map((f) => (
                <label
                  key={f.id}
                  className="flex cursor-pointer items-center gap-2 px-2 py-1 hover:bg-white/5"
                >
                  <input
                    type="checkbox"
                    checked={selectedIds.has(f.id)}
                    onChange={() => onToggle(f.id)}
                    className="accent-cyan-500"
                  />
                  <span className="truncate">{f.name}</span>
                </label>
              ))
            )}
          </div>
          <p className="mt-1 text-[10px] text-gray-500">
            {selectedIds.size} selected. Click a district on the map or tick it here to set the
            AOI. Passes and the report use those polygons only (no extra buffer).
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <button
              onClick={onUseSelected}
              disabled={!selectedIds.size}
              className="rounded bg-cyan-600 px-2 py-1 text-[11px] font-medium hover:bg-cyan-500 disabled:opacity-40"
            >
              Use selected as AOI
            </button>
            <button
              onClick={onClear}
              className="rounded bg-white/5 px-2 py-1 text-[11px] ring-1 ring-white/10 hover:bg-white/10"
            >
              Clear
            </button>
            <button
              onClick={onExportAoi}
              disabled={!selectedIds.size || exporting}
              className="inline-flex items-center gap-1 rounded bg-white/5 px-2 py-1 text-[11px] ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-40"
            >
              {exporting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
              Export AOI zip
            </button>
            <button
              onClick={() => void downloadOriginal()}
              disabled={layerId == null || busy === 'dl'}
              className="rounded bg-white/5 px-2 py-1 text-[11px] text-gray-400 ring-1 ring-white/10 hover:bg-white/10"
            >
              Download layer zip
            </button>
          </div>
        </>
      )}
      {error && <p className="mt-1 text-[11px] text-red-400">{error}</p>}
    </section>
  );
}
