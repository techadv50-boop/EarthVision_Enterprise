import { useState } from 'react';
import { Download, Eye, Satellite, Search, X } from 'lucide-react';
import { useMapStore } from '../store/mapStore';
import {
  catalogService,
  type CollectionName,
  type SceneSummary,
} from '../services/catalogService';
import { getErrorMessage } from '../services/api';
import type { GlobeController } from '../map/Globe';
import { flyTo } from '../map/cesiumViewer';

interface Props {
  globe: GlobeController | null;
}

const COLLECTIONS: CollectionName[] = [
  'SENTINEL-1',
  'SENTINEL-2',
  'LANDSAT-8',
  'LANDSAT-9',
  'MODIS',
];

export function CatalogPanel({ globe }: Props) {
  const {
    activePanel,
    setActivePanel,
    aoiGeoJson,
    setScenes,
    scenes,
    setSelectedScene,
    selectedScene,
  } = useMapStore();
  const [collections, setCollections] = useState<CollectionName[]>(['SENTINEL-2']);
  const [cloudMax, setCloudMax] = useState(30);
  const [startDate, setStartDate] = useState('2024-01-01');
  const [endDate, setEndDate] = useState('2025-12-31');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authStatus, setAuthStatus] = useState<string>('unknown');
  const [message, setMessage] = useState<string | null>(null);

  if (activePanel !== 'catalog') return null;

  const toggleCollection = (c: CollectionName) => {
    setCollections((prev) =>
      prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c],
    );
  };

  const bboxFromAoi = (): number[] | null => {
    if (!aoiGeoJson || aoiGeoJson.geometry.type !== 'Polygon') return null;
    const ring = aoiGeoJson.geometry.coordinates[0];
    const lons = ring.map((c: number[]) => c[0]);
    const lats = ring.map((c: number[]) => c[1]);
    return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
  };

  const search = async () => {
    setLoading(true);
    setError(null);
    setMessage(null);
    try {
      const status = await catalogService.authStatus();
      setAuthStatus(status.configured ? 'CDSE connected' : 'Demo catalog mode');
      const result = await catalogService.search({
        collections: collections.length ? collections : ['SENTINEL-2'],
        start_date: new Date(startDate).toISOString(),
        end_date: new Date(endDate).toISOString(),
        cloud_cover_max: cloudMax,
        bbox: bboxFromAoi() ?? [2.0, 48.5, 2.8, 49.1],
        max_results: 40,
      });
      setScenes(result.items);
      setMessage(`Found ${result.total} scenes`);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const selectScene = (scene: SceneSummary) => {
    setSelectedScene(scene);
    if (scene.center && globe?.getViewer()) {
      flyTo(globe.getViewer()!, scene.center[0], scene.center[1], 400_000);
    }
  };

  const download = async (scene: SceneSummary) => {
    try {
      const result = await catalogService.download(scene.id, scene.collection);
      setMessage(result.message || 'Download queued');
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  return (
    <aside className="pointer-events-auto absolute right-3 top-20 z-20 w-[min(100%-1.5rem,26rem)] animate-fade-up md:right-4">
      <div className="ev-panel flex max-h-[calc(100vh-8rem)] flex-col p-3">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="font-display text-sm font-semibold">Satellite Catalog</h2>
            <p className="text-[10px] text-earth-400">{authStatus}</p>
          </div>
          <button type="button" className="ev-btn-ghost p-1" onClick={() => setActivePanel('none')}>
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mb-2 flex flex-wrap gap-1">
          {COLLECTIONS.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => toggleCollection(c)}
              className={`rounded-md px-2 py-1 text-[10px] ${
                collections.includes(c)
                  ? 'bg-orbit-500/25 text-orbit-400'
                  : 'bg-earth-800 text-earth-400'
              }`}
            >
              {c}
            </button>
          ))}
        </div>

        <div className="mb-2 grid grid-cols-2 gap-2">
          <div>
            <label className="ev-label">Start</label>
            <input type="date" className="ev-input" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </div>
          <div>
            <label className="ev-label">End</label>
            <input type="date" className="ev-input" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
        </div>
        <div className="mb-3">
          <label className="ev-label">Cloud cover ≤ {cloudMax}%</label>
          <input
            type="range"
            min={0}
            max={100}
            value={cloudMax}
            onChange={(e) => setCloudMax(Number(e.target.value))}
            className="w-full"
          />
        </div>
        <button type="button" className="ev-btn-primary w-full" onClick={search} disabled={loading}>
          <Search className="h-4 w-4" />
          {loading ? 'Searching…' : 'Search Scenes'}
        </button>
        {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
        {message && <p className="mt-2 text-xs text-orbit-400">{message}</p>}

        <ul className="mt-3 flex-1 space-y-2 overflow-y-auto">
          {scenes.map((scene) => (
            <li
              key={scene.id}
              className={`rounded-lg border p-2 ${
                selectedScene?.id === scene.id
                  ? 'border-orbit-500 bg-orbit-500/10'
                  : 'border-earth-700/60 bg-earth-950/40'
              }`}
            >
              <button type="button" className="w-full text-left" onClick={() => selectScene(scene)}>
                <div className="flex items-start gap-2">
                  <Satellite className="mt-0.5 h-4 w-4 shrink-0 text-orbit-400" />
                  <div>
                    <div className="line-clamp-2 text-[11px] font-medium text-earth-100">
                      {scene.name}
                    </div>
                    <div className="mt-1 text-[10px] text-earth-400">
                      {scene.collection}
                      {scene.cloud_cover != null && ` · ${scene.cloud_cover}% cloud`}
                      {scene.sensing_time && ` · ${new Date(scene.sensing_time).toLocaleDateString()}`}
                    </div>
                  </div>
                </div>
              </button>
              <div className="mt-2 flex gap-2">
                <a
                  className="ev-btn-secondary flex-1 text-[10px]"
                  href={catalogService.previewUrl(scene.id)}
                  target="_blank"
                  rel="noreferrer"
                >
                  <Eye className="h-3 w-3" /> Preview
                </a>
                <button
                  type="button"
                  className="ev-btn-secondary flex-1 text-[10px]"
                  onClick={() => download(scene)}
                >
                  <Download className="h-3 w-3" /> Cache
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
