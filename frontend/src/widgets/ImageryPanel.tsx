import { useEffect, useState } from 'react';
import {
  Satellite, Download, Search, Cloud, Calendar, Loader2, Link2, Unlink, Eye, Layers,
} from 'lucide-react';
import { imageryApi } from '@/services/api';
import { useMapStore } from '@/store/mapStore';
import { useUIStore } from '@/store/uiStore';

const COLLECTIONS = ['SENTINEL-1', 'SENTINEL-2', 'LANDSAT', 'MODIS'];

export default function ImageryPanel() {
  const [collection, setCollection] = useState('SENTINEL-2');
  const [startDate, setStartDate] = useState('2024-01-01');
  const [endDate, setEndDate] = useState('2024-12-31');
  const [cloudCover, setCloudCover] = useState(30);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [useAoi, setUseAoi] = useState(true);
  const [copernicusConnected, setCopernicusConnected] = useState(false);
  const {
    scenes,
    setScenes,
    selectedScene,
    setSelectedScene,
    flyTo,
    drawnGeometries,
    aois,
    renderFootprints,
    addSceneImageryLayer,
  } = useMapStore();
  const { showNotification } = useUIStore();

  useEffect(() => {
    void (async () => {
      try {
        const { data } = await imageryApi.copernicus.status();
        setCopernicusConnected(Boolean(data.connected));
      } catch {
        setCopernicusConnected(false);
      }
      try {
        const { data } = await imageryApi.footprints();
        if (Array.isArray(data) && data.length > 0) {
          renderFootprints(data);
        }
      } catch {
        /* ignore */
      }
    })();
  }, [renderFootprints]);

  const getAoiGeojson = (): string | undefined => {
    if (!useAoi) return undefined;
    const drawn = [...drawnGeometries].reverse().find((f) => f.geometry.type === 'Polygon');
    if (drawn) return JSON.stringify(drawn);
    if (aois[0]) return aois[0].geojson;
    return undefined;
  };

  const handleConnectCopernicus = async () => {
    try {
      const { data } = await imageryApi.copernicus.authUrl();
      if (data.authorization_url) {
        window.location.href = data.authorization_url;
      } else {
        showNotification('Configure COPERNICUS_CLIENT_ID in .env', 'error');
      }
    } catch {
      showNotification('Failed to start Copernicus OAuth', 'error');
    }
  };

  const handleSearch = async () => {
    setLoading(true);
    try {
      const payload: Record<string, unknown> = {
        collection,
        start_date: new Date(startDate).toISOString(),
        end_date: new Date(endDate).toISOString(),
        cloud_cover_max: cloudCover,
        limit: 50,
      };
      const aoi = getAoiGeojson();
      if (aoi) payload.aoi_geojson = aoi;

      const { data } = await imageryApi.search(payload);
      setScenes(data.scenes);
      renderFootprints(data.scenes);
      showNotification(`Found ${data.total} scenes`, 'success');
    } catch {
      showNotification('Scene search failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async (scene: (typeof scenes)[0]) => {
    setDownloading(scene.scene_id);
    try {
      const { data } = await imageryApi.download(scene.scene_id, collection, {
        footprint_geojson: scene.footprint_geojson,
        cloud_cover: scene.cloud_cover,
        acquisition_date: scene.acquisition_date,
        metadata: scene.metadata,
      });
      addSceneImageryLayer(scene.scene_id);
      showNotification(
        `Scene cached: ${(data.file_size_bytes / 1024 / 1024).toFixed(1)} MB — layer added`,
        'success',
      );
    } catch {
      showNotification('Download failed', 'error');
    } finally {
      setDownloading(null);
    }
  };

  const handleSelectScene = (scene: (typeof scenes)[0]) => {
    setSelectedScene(scene);
    if (scene.footprint_geojson) {
      try {
        const geo = JSON.parse(scene.footprint_geojson);
        const ring = geo.coordinates?.[0] || geo.geometry?.coordinates?.[0];
        if (ring?.[0]) {
          const lons = ring.map((c: number[]) => c[0]);
          const lats = ring.map((c: number[]) => c[1]);
          flyTo(
            (Math.min(...lons) + Math.max(...lons)) / 2,
            (Math.min(...lats) + Math.max(...lats)) / 2,
            100000,
          );
        }
      } catch {
        /* ignore */
      }
    }
  };

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-2">
        <Satellite className="w-4 h-4" /> Satellite Imagery
      </h3>

      <button
        onClick={() => void handleConnectCopernicus()}
        className={`w-full flex items-center justify-center gap-2 text-xs px-3 py-2 rounded border ${
          copernicusConnected
            ? 'border-green-700 bg-green-900/20 text-green-300'
            : 'border-gray-700 hover:border-earth-500'
        }`}
      >
        {copernicusConnected ? <Link2 className="w-3.5 h-3.5" /> : <Unlink className="w-3.5 h-3.5" />}
        {copernicusConnected ? 'Copernicus Connected' : 'Connect Copernicus CDSE'}
      </button>

      <div className="grid grid-cols-2 gap-2">
        {COLLECTIONS.map((c) => (
          <button
            key={c}
            onClick={() => setCollection(c)}
            className={`px-2 py-1.5 text-xs rounded border transition-colors ${
              collection === c
                ? 'border-earth-500 bg-earth-600/20 text-earth-300'
                : 'border-gray-700 hover:border-gray-600'
            }`}
          >
            {c}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-xs text-gray-500 flex items-center gap-1 mb-1">
            <Calendar className="w-3 h-3" /> Start
          </label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="input-field text-xs"
          />
        </div>
        <div>
          <label className="text-xs text-gray-500 flex items-center gap-1 mb-1">
            <Calendar className="w-3 h-3" /> End
          </label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="input-field text-xs"
          />
        </div>
      </div>

      <div>
        <label className="text-xs text-gray-500 flex items-center gap-1 mb-1">
          <Cloud className="w-3 h-3" /> Max Cloud Cover: {cloudCover}%
        </label>
        <input
          type="range"
          min={0}
          max={100}
          value={cloudCover}
          onChange={(e) => setCloudCover(Number(e.target.value))}
          className="w-full"
        />
      </div>

      <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
        <input
          type="checkbox"
          checked={useAoi}
          onChange={(e) => setUseAoi(e.target.checked)}
          className="rounded"
        />
        Filter by AOI / last drawing
      </label>

      <button
        onClick={() => void handleSearch()}
        disabled={loading}
        className="btn-primary w-full flex items-center justify-center gap-2"
      >
        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
        Search Scenes
      </button>

      <div className="max-h-56 overflow-y-auto space-y-1">
        {scenes.map((scene) => (
          <div
            key={scene.scene_id}
            onClick={() => handleSelectScene(scene)}
            className={`p-2 rounded cursor-pointer transition-colors ${
              selectedScene?.scene_id === scene.scene_id
                ? 'bg-earth-600/20 border border-earth-500'
                : 'hover:bg-gray-800'
            }`}
          >
            {scene.preview_url && (
              <img
                src={scene.preview_url}
                alt={scene.scene_id}
                className="w-full h-16 object-cover rounded mb-2 bg-gray-900"
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = 'none';
                }}
              />
            )}
            <div className="flex items-center justify-between gap-1">
              <div className="text-xs font-mono truncate flex-1">{scene.scene_id}</div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  void handleDownload(scene);
                }}
                className="p-1 hover:text-earth-400"
                title="Download & add layer"
                disabled={downloading === scene.scene_id}
              >
                {downloading === scene.scene_id ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Download className="w-3 h-3" />
                )}
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  addSceneImageryLayer(scene.scene_id);
                  showNotification('Scene layer added to globe', 'info');
                }}
                className="p-1 hover:text-earth-400"
                title="Add raster layer"
              >
                <Layers className="w-3 h-3" />
              </button>
            </div>
            <div className="text-xs text-gray-500 mt-1 flex items-center gap-1">
              <Eye className="w-3 h-3" />
              {new Date(scene.acquisition_date).toLocaleDateString()}
              {scene.cloud_cover != null && ` · ${scene.cloud_cover}% cloud`}
              {scene.metadata?.mock ? ' · demo' : ''}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
