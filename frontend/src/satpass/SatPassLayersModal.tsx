import { useEffect, useState } from 'react';
import { Loader2, Trash2, Upload, X } from 'lucide-react';
import { aoiLayerApi, type AoiLayerSummary } from '@/services/api';

export default function SatPassLayersModal({ onClose }: { onClose: () => void }) {
  const [layers, setLayers] = useState<AoiLayerSummary[]>([]);
  const [name, setName] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const load = async () => {
    try {
      const { data } = await aoiLayerApi.list();
      setLayers(data);
    } catch {
      setError('Could not load layers.');
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const upload = async () => {
    if (!file) {
      setError('Choose a zipped shapefile (.zip).');
      return;
    }
    setBusy('up');
    setError('');
    try {
      await aoiLayerApi.create(file, name);
      setName('');
      setFile(null);
      await load();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Upload failed. Use a .zip that contains .shp, .shx, and .dbf.');
    } finally {
      setBusy('');
    }
  };

  const remove = async (id: number) => {
    setBusy(`del-${id}`);
    setError('');
    try {
      await aoiLayerApi.remove(id);
      await load();
    } catch {
      setError('Could not remove that layer.');
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-lg rounded-lg bg-gray-950 p-4 text-gray-100 ring-1 ring-white/15">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Shapefile layers (admin)</h2>
          <button onClick={onClose} className="rounded p-1 text-gray-400 hover:bg-white/10">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mb-3 text-[11px] text-gray-500">
          Upload district or city boundaries as a zip. Users can click those features as Predict
          AOIs. Only admins can add or remove layers.
        </p>
        <div className="mb-3 space-y-2 rounded bg-gray-900 p-2 ring-1 ring-white/10">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Layer name (e.g. Pakistan districts)"
            className="w-full rounded bg-black/40 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10"
          />
          <input
            type="file"
            accept=".zip,application/zip"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="w-full text-[11px] text-gray-400"
          />
          <button
            onClick={() => void upload()}
            disabled={busy === 'up'}
            className="inline-flex items-center gap-1 rounded bg-cyan-600 px-3 py-1.5 text-sm hover:bg-cyan-500 disabled:opacity-50"
          >
            {busy === 'up' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            Add layer
          </button>
        </div>
        <div className="max-h-64 space-y-1 overflow-auto">
          {layers.length === 0 && <p className="text-[11px] text-gray-500">No layers stored yet.</p>}
          {layers.map((l) => (
            <div
              key={l.id}
              className="flex items-center gap-2 rounded bg-gray-900 px-2 py-1.5 text-sm ring-1 ring-white/10"
            >
              <div className="min-w-0 flex-1">
                <div className="truncate">{l.name}</div>
                <div className="truncate text-[10px] text-gray-500">
                  {l.feature_count} features · {l.original_filename}
                </div>
              </div>
              <button
                onClick={() => void remove(l.id)}
                disabled={busy === `del-${l.id}`}
                className="rounded p-1 text-gray-400 hover:bg-white/10 hover:text-red-400"
                title="Remove layer"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
        {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
      </div>
    </div>
  );
}
