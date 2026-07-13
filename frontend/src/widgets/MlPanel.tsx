import { useState } from 'react';
import { Brain, X } from 'lucide-react';
import { useMapStore } from '../store/mapStore';
import { mlService } from '../services/mlService';
import { getErrorMessage } from '../services/api';

export function MlPanel() {
  const { activePanel, setActivePanel } = useMapStore();
  const [algorithm, setAlgorithm] = useState<'random_forest' | 'svm' | 'deep_learning'>(
    'random_forest',
  );
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [changeResult, setChangeResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (activePanel !== 'ml') return null;

  const train = async () => {
    setLoading(true);
    setError(null);
    try {
      const dataset = await mlService.getDemoDataset(400);
      const trained = await mlService.train({
        algorithm,
        task: 'land_cover',
        features: dataset.features,
        labels: dataset.labels,
      });
      setResult(trained);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const runChange = async () => {
    setLoading(true);
    setError(null);
    try {
      const before = Array.from({ length: 200 }, (_, i) => 0.3 + Math.sin(i / 10) * 0.1);
      const after = before.map((v, i) => v + (i > 100 ? 0.25 : 0.02));
      const data = await mlService.changeDetection(before, after, 0.12);
      setChangeResult(data);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <aside className="pointer-events-auto absolute right-3 top-20 z-20 w-[min(100%-1.5rem,24rem)] animate-fade-up md:right-4">
      <div className="ev-panel max-h-[calc(100vh-8rem)] overflow-y-auto p-3">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-sm font-semibold">AI / Machine Learning</h2>
          <button type="button" className="ev-btn-ghost p-1" onClick={() => setActivePanel('none')}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mb-3 text-xs text-earth-400">
          Train land-cover classifiers and run change detection on spectral feature vectors.
        </p>
        <label className="ev-label">Algorithm</label>
        <select
          className="ev-input mb-3"
          value={algorithm}
          onChange={(e) => setAlgorithm(e.target.value as typeof algorithm)}
        >
          <option value="random_forest">Random Forest</option>
          <option value="svm">Support Vector Machine</option>
          <option value="deep_learning">Deep Learning (MLP)</option>
        </select>
        <button type="button" className="ev-btn-primary mb-2 w-full" onClick={train} disabled={loading}>
          <Brain className="h-4 w-4" />
          {loading ? 'Training…' : 'Train Land Cover Model'}
        </button>
        <button type="button" className="ev-btn-secondary w-full" onClick={runChange} disabled={loading}>
          Run Change Detection
        </button>
        {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
        {result && (
          <div className="mt-3 rounded-lg bg-earth-950/60 p-3 text-xs">
            <div className="mb-1 font-medium text-orbit-400">Training Results</div>
            <div>Accuracy: {Number(result.accuracy).toFixed(3)}</div>
            <div>Precision: {Number(result.precision).toFixed(3)}</div>
            <div>Recall: {Number(result.recall).toFixed(3)}</div>
            <div>F1: {Number(result.f1_score).toFixed(3)}</div>
            <div className="mt-1 truncate text-earth-500">Model: {String(result.model_id)}</div>
          </div>
        )}
        {changeResult && (
          <div className="mt-3 rounded-lg bg-earth-950/60 p-3 text-xs">
            <div className="mb-1 font-medium text-soil-400">Change Detection</div>
            <div>Change ratio: {(Number(changeResult.change_ratio) * 100).toFixed(1)}%</div>
            <div>Changed pixels: {String(changeResult.significant_change_pixels)}</div>
            <div>Mean Δ: {Number(changeResult.mean_difference).toFixed(4)}</div>
          </div>
        )}
      </div>
    </aside>
  );
}
