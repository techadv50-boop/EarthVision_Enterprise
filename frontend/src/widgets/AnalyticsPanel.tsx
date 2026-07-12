import { useState } from 'react';
import {
  BarChart3, TrendingUp, Brain, Loader2, LineChart as LineChartIcon, Droplets,
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid,
} from 'recharts';
import { analyticsApi } from '@/services/api';
import { useMapStore } from '@/store/mapStore';
import { useUIStore } from '@/store/uiStore';

const INDICES = ['NDVI', 'NDWI', 'NDBI', 'SAVI', 'BSI', 'LST'];
const ML_MODELS = ['random_forest', 'svm', 'deep_learning'];

const DETECTIONS = [
  { id: 'water', label: 'Water', api: analyticsApi.detectWater },
  { id: 'flood', label: 'Flood', api: analyticsApi.detectFlood },
  { id: 'building', label: 'Building', api: analyticsApi.detectBuilding },
  { id: 'road', label: 'Road', api: analyticsApi.detectRoad },
  { id: 'urban', label: 'Urban', api: analyticsApi.detectUrban },
] as const;

export default function AnalyticsPanel() {
  const [selectedIndex, setSelectedIndex] = useState('NDVI');
  const [selectedModel, setSelectedModel] = useState('random_forest');
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState<Record<string, number> | null>(null);
  const [histogram, setHistogram] = useState<Array<{ bin: string; count: number }> | null>(null);
  const [timeSeries, setTimeSeries] = useState<Array<{ date: string; value: number }> | null>(null);
  const { selectedScene, scenes, drawnGeometries, addAnalysisLayer } = useMapStore();
  const { showNotification } = useUIStore();

  const scene = selectedScene || scenes[0];

  const aoiGeojson = (() => {
    const drawn = [...drawnGeometries].reverse().find((f) => f.geometry.type === 'Polygon');
    return drawn ? JSON.stringify(drawn) : undefined;
  })();

  const applyTileUrl = (tileUrl?: string) => {
    if (!tileUrl) return;
    const absolute = tileUrl.startsWith('http')
      ? tileUrl
      : `${window.location.origin}${tileUrl}`;
    addAnalysisLayer(absolute);
  };

  const handleComputeIndex = async () => {
    if (!scene) {
      showNotification('Select a scene first', 'error');
      return;
    }
    setLoading(true);
    try {
      const { data } = await analyticsApi.computeIndex({
        index_type: selectedIndex,
        scene_id: scene.scene_id,
        collection: scene.collection,
        aoi_geojson: aoiGeojson,
      });
      setStats(data.statistics);
      applyTileUrl(data.tile_url);
      if (data.job_id) {
        try {
          const hist = await analyticsApi.histogram(data.job_id);
          const bins = hist.data.bins as number[];
          const counts = hist.data.counts as number[];
          setHistogram(
            counts.map((count, i) => ({
              bin: ((bins[i] + bins[i + 1]) / 2).toFixed(2),
              count,
            }))
          );
        } catch {
          /* histogram optional */
        }
      }
      showNotification(`${selectedIndex} computed successfully`, 'success');
    } catch {
      showNotification('Index computation failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleTimeSeries = async () => {
    if (scenes.length < 2) {
      showNotification('Search for at least 2 scenes first', 'error');
      return;
    }
    setLoading(true);
    try {
      const { data } = await analyticsApi.timeSeries({
        index_type: selectedIndex,
        collection: scenes[0].collection,
        scene_ids: scenes.slice(0, 8).map((s) => s.scene_id),
        aoi_geojson: aoiGeojson,
      });
      setTimeSeries(
        data.points.map((p: { date: string; value: number }) => ({
          date: new Date(p.date).toLocaleDateString(),
          value: Number(p.value.toFixed(4)),
        }))
      );
      showNotification('Time series computed', 'success');
    } catch {
      showNotification('Time series failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleClassify = async () => {
    if (!scene) return;
    setLoading(true);
    try {
      const { data } = await analyticsApi.classify({
        model_type: selectedModel,
        scene_id: scene.scene_id,
        collection: scene.collection,
        num_classes: 5,
      });
      applyTileUrl(data.tile_url);
      showNotification(`Classification ${data.status}`, 'success');
    } catch {
      showNotification('Classification failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleChangeDetection = async () => {
    if (scenes.length < 2) {
      showNotification('Need at least 2 scenes', 'error');
      return;
    }
    setLoading(true);
    try {
      const { data } = await analyticsApi.changeDetection({
        scene_id_before: scenes[1].scene_id,
        scene_id_after: scenes[0].scene_id,
        collection: scenes[0].collection,
        method: 'difference',
      });
      applyTileUrl(data.tile_url);
      showNotification('Change detection complete', 'success');
    } catch {
      showNotification('Change detection failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleDetect = async (detection: (typeof DETECTIONS)[number]) => {
    if (!scene) {
      showNotification('Select a scene first', 'error');
      return;
    }
    setLoading(true);
    try {
      const payload: Record<string, unknown> = {
        scene_id: scene.scene_id,
        collection: scene.collection,
        aoi_geojson: aoiGeojson,
      };
      if (detection.id === 'flood' && scenes.length >= 2) {
        payload.scene_id_before = scenes[1].scene_id;
      }
      const { data } = await detection.api(payload);
      applyTileUrl(data.tile_url);
      showNotification(`${detection.label} detection ${data.status}`, 'success');
    } catch {
      showNotification(`${detection.label} detection failed`, 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-2">
        <BarChart3 className="w-4 h-4" /> Analytics
      </h3>

      <div>
        <label className="text-xs text-gray-500 mb-2 block">Spectral Index</label>
        <div className="grid grid-cols-3 gap-1">
          {INDICES.map((idx) => (
            <button
              key={idx}
              onClick={() => setSelectedIndex(idx)}
              className={`px-2 py-1 text-xs rounded border ${
                selectedIndex === idx ? 'border-earth-500 bg-earth-600/20' : 'border-gray-700'
              }`}
            >
              {idx}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2 mt-2">
          <button
            onClick={handleComputeIndex}
            disabled={loading}
            className="btn-primary flex items-center justify-center gap-1 text-xs"
          >
            {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <TrendingUp className="w-3 h-3" />}
            Compute
          </button>
          <button
            onClick={handleTimeSeries}
            disabled={loading}
            className="btn-secondary flex items-center justify-center gap-1 text-xs"
          >
            <LineChartIcon className="w-3 h-3" /> Series
          </button>
        </div>
      </div>

      {stats && (
        <div className="panel p-3 space-y-1">
          <div className="text-xs text-gray-500 uppercase">Statistics</div>
          {Object.entries(stats).map(([key, val]) => (
            <div key={key} className="flex justify-between text-sm">
              <span className="text-gray-400">{key}</span>
              <span className="font-mono">{Number(val).toFixed(4)}</span>
            </div>
          ))}
        </div>
      )}

      {histogram && (
        <div className="h-32">
          <div className="text-xs text-gray-500 mb-1">Histogram</div>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={histogram}>
              <XAxis dataKey="bin" hide />
              <YAxis hide />
              <Tooltip
                contentStyle={{ background: '#1f2937', border: '1px solid #374151', fontSize: 11 }}
              />
              <Bar dataKey="count" fill="#22c55e" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {timeSeries && (
        <div className="h-36">
          <div className="text-xs text-gray-500 mb-1">Time Series</div>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={timeSeries}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#9ca3af' }} />
              <YAxis tick={{ fontSize: 9, fill: '#9ca3af' }} width={36} />
              <Tooltip
                contentStyle={{ background: '#1f2937', border: '1px solid #374151', fontSize: 11 }}
              />
              <Line type="monotone" dataKey="value" stroke="#38bdf8" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div>
        <label className="text-xs text-gray-500 mb-2 block flex items-center gap-1">
          <Brain className="w-3 h-3" /> Machine Learning
        </label>
        <select
          value={selectedModel}
          onChange={(e) => setSelectedModel(e.target.value)}
          className="input-field text-sm mb-2"
        >
          {ML_MODELS.map((m) => (
            <option key={m} value={m}>
              {m.replace('_', ' ').toUpperCase()}
            </option>
          ))}
        </select>
        <div className="grid grid-cols-2 gap-2">
          <button onClick={handleClassify} disabled={loading} className="btn-secondary text-xs">
            Classify
          </button>
          <button onClick={handleChangeDetection} disabled={loading} className="btn-secondary text-xs">
            Change Detect
          </button>
        </div>
      </div>

      <div>
        <label className="text-xs text-gray-500 mb-2 block flex items-center gap-1">
          <Droplets className="w-3 h-3" /> Thematic Detection
        </label>
        <div className="grid grid-cols-3 gap-1">
          {DETECTIONS.map((d) => (
            <button
              key={d.id}
              onClick={() => void handleDetect(d)}
              disabled={loading}
              className="btn-secondary text-xs py-1.5"
            >
              {d.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
