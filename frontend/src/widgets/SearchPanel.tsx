import { useState } from 'react';
import { MapPin, Navigation, Search, X } from 'lucide-react';
import { gisService, type GeocodeResult } from '../services/gisService';
import { useMapStore } from '../store/mapStore';
import { getErrorMessage } from '../services/api';
import type { GlobeController } from '../map/Globe';

interface Props {
  globe: GlobeController | null;
}

export function SearchPanel({ globe }: Props) {
  const { activePanel, setActivePanel, addMarker } = useMapStore();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<GeocodeResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (activePanel !== 'search') return null;

  const onSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const data = await gisService.geocode(query.trim());
      setResults(data);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const goTo = (result: GeocodeResult) => {
    globe?.flyTo(result.longitude, result.latitude, 80_000);
    addMarker({
      lon: result.longitude,
      lat: result.latitude,
      label: result.display_name.split(',')[0],
    });
  };

  return (
    <aside className="pointer-events-auto absolute left-3 top-20 z-20 w-[min(100%-1.5rem,22rem)] animate-fade-up md:left-4">
      <div className="ev-panel p-3">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-sm font-semibold text-earth-50">Location Search</h2>
          <button type="button" className="ev-btn-ghost p-1" onClick={() => setActivePanel('none')}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <form onSubmit={onSearch} className="flex gap-2">
          <input
            className="ev-input"
            placeholder="City, landmark, or lat, lon"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit" className="ev-btn-primary px-3" disabled={loading}>
            <Search className="h-4 w-4" />
          </button>
        </form>
        {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
        <ul className="mt-3 max-h-72 space-y-1 overflow-y-auto">
          {results.map((r) => (
            <li key={`${r.longitude}-${r.latitude}-${r.display_name}`}>
              <button
                type="button"
                onClick={() => goTo(r)}
                className="flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left hover:bg-earth-800/80"
              >
                <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-orbit-400" />
                <span className="text-xs text-earth-200">{r.display_name}</span>
              </button>
            </li>
          ))}
        </ul>
        <button
          type="button"
          className="ev-btn-secondary mt-3 w-full text-xs"
          onClick={() => globe?.flyTo(0, 20, 18_000_000)}
        >
          <Navigation className="h-3.5 w-3.5" />
          Reset Camera
        </button>
      </div>
    </aside>
  );
}
