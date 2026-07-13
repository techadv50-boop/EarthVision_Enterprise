import { useState } from 'react';
import { BarChart3, X } from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useMapStore } from '../store/mapStore';
import { analyticsService, type IndexName } from '../services/analyticsService';
import { getErrorMessage } from '../services/api';

const INDICES: IndexName[] = ['NDVI', 'NDWI', 'NDBI', 'SAVI', 'BSI', 'LST'];

export function AnalyticsPanel() {
  const {
    activePanel,
    setActivePanel,
    selectedIndex,
    setSelectedIndex,
    indexResult,
    setIndexResult,
    selectedScene,
  } = useMapStore();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (activePanel !== 'analytics') return null;

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await analyticsService.computeIndex(
        selectedIndex,
        selectedScene?.id,
      );
      setIndexResult(result);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const histData =
    indexResult?.histogram.counts.map((count, i) => ({
      bin: Number(indexResult.histogram.edges[i].toFixed(2)),
      count,
    })) ?? [];

  return (
    <aside className="pointer-events-auto absolute right-3 top-20 z-20 w-[min(100%-1.5rem,26rem)] animate-fade-up md:right-4">
      <div className="ev-panel max-h-[calc(100vh-8rem)] overflow-y-auto p-3">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-sm font-semibold">Spectral Analytics</h2>
          <button type="button" className="ev-btn-ghost p-1" onClick={() => setActivePanel('none')}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="mb-3 flex flex-wrap gap-1">
          {INDICES.map((idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => setSelectedIndex(idx)}
              className={`rounded-md px-2 py-1 text-[10px] font-medium ${
                selectedIndex === idx
                  ? 'bg-orbit-500 text-earth-950'
                  : 'bg-earth-800 text-earth-300'
              }`}
            >
              {idx}
            </button>
          ))}
        </div>
        <button type="button" className="ev-btn-primary w-full" onClick={run} disabled={loading}>
          <BarChart3 className="h-4 w-4" />
          {loading ? 'Computing…' : `Compute ${selectedIndex}`}
        </button>
        {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
        {indexResult && (
          <div className="mt-3 space-y-3">
            {indexResult.preview_base64 && (
              <img
                src={`data:image/png;base64,${indexResult.preview_base64}`}
                alt={`${indexResult.index} preview`}
                className="w-full rounded-lg border border-earth-700"
              />
            )}
            <div className="grid grid-cols-3 gap-2 text-center">
              {[
                ['Mean', indexResult.mean],
                ['Std', indexResult.std],
                ['Median', indexResult.median],
                ['Min', indexResult.min],
                ['Max', indexResult.max],
                ['Pixels', indexResult.valid_pixels],
              ].map(([label, value]) => (
                <div key={String(label)} className="rounded-lg bg-earth-950/60 p-2">
                  <div className="text-[9px] uppercase tracking-wider text-earth-500">
                    {label}
                  </div>
                  <div className="font-mono text-xs text-earth-100">
                    {typeof value === 'number' ? value.toFixed(3) : value}
                  </div>
                </div>
              ))}
            </div>
            <div className="h-40">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={histData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#245947" />
                  <XAxis dataKey="bin" tick={{ fill: '#8bb5a3', fontSize: 9 }} />
                  <YAxis tick={{ fill: '#8bb5a3', fontSize: 9 }} />
                  <Tooltip
                    contentStyle={{
                      background: '#0f2a22',
                      border: '1px solid #245947',
                      fontSize: 11,
                    }}
                  />
                  <Bar dataKey="count" fill="#3ba3c7" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
