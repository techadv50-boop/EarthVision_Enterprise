import { useState } from 'react';
import { Search, MapPin, Loader2, Crosshair } from 'lucide-react';
import { geoApi } from '@/services/api';
import { useMapStore } from '@/store/mapStore';
import { useUIStore } from '@/store/uiStore';

function parseCoordinateQuery(query: string): { longitude: number; latitude: number } | null {
  const cleaned = query.trim().replace(/,/g, ' ').replace(/\s+/g, ' ');
  const parts = cleaned.split(' ');
  if (parts.length !== 2) return null;
  const a = Number(parts[0]);
  const b = Number(parts[1]);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;

  // Prefer lat,lon when first value is a valid latitude
  if (Math.abs(a) <= 90 && Math.abs(b) <= 180) {
    return { latitude: a, longitude: b };
  }
  // lon,lat fallback
  if (Math.abs(a) <= 180 && Math.abs(b) <= 90) {
    return { longitude: a, latitude: b };
  }
  return null;
}

export default function SearchPanel() {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const {
    searchResults,
    setSearchResults,
    flyTo,
    renderSearchMarkers,
    clearSearchMarkers,
    mousePosition,
  } = useMapStore();
  const { showNotification } = useUIStore();

  const handleSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const coords = parseCoordinateQuery(query);
      if (coords) {
        const results = [
          {
            name: `${coords.latitude.toFixed(5)}, ${coords.longitude.toFixed(5)}`,
            display_name: 'Coordinate search',
            longitude: coords.longitude,
            latitude: coords.latitude,
          },
        ];
        setSearchResults(results);
        renderSearchMarkers(results);
        flyTo(coords.longitude, coords.latitude, 25000);
        showNotification('Flew to coordinates', 'success');
        return;
      }

      const { data } = await geoApi.search(query);
      setSearchResults(data);
      renderSearchMarkers(data);
      if (data.length === 0) {
        clearSearchMarkers();
        showNotification('No results found', 'info');
      } else if (data.length === 1) {
        flyTo(data[0].longitude, data[0].latitude, 50000);
      }
    } catch {
      showNotification('Search failed', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleSelect = (result: (typeof searchResults)[0]) => {
    flyTo(result.longitude, result.latitude, 50000);
    renderSearchMarkers([result]);
    showNotification(`Navigated to ${result.name}`, 'success');
  };

  const handleUseMouse = () => {
    const label = `${mousePosition.latitude.toFixed(5)}, ${mousePosition.longitude.toFixed(5)}`;
    setQuery(label);
    const results = [
      {
        name: label,
        display_name: 'Current cursor position',
        longitude: mousePosition.longitude,
        latitude: mousePosition.latitude,
      },
    ];
    setSearchResults(results);
    renderSearchMarkers(results);
    flyTo(mousePosition.longitude, mousePosition.latitude, 25000);
  };

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">Location Search</h3>
      <div className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && void handleSearch()}
          placeholder="City, address, or lat, lon..."
          className="input-field text-sm"
        />
        <button onClick={() => void handleSearch()} disabled={loading} className="btn-primary px-3">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
        </button>
      </div>
      <button onClick={handleUseMouse} className="btn-secondary w-full text-xs flex items-center justify-center gap-2">
        <Crosshair className="w-3.5 h-3.5" />
        Use cursor coordinates
      </button>

      <div className="max-h-64 overflow-y-auto space-y-1">
        {searchResults.map((result, i) => (
          <button
            key={`${result.longitude}-${result.latitude}-${i}`}
            onClick={() => handleSelect(result)}
            className="w-full text-left p-2 rounded hover:bg-gray-800 transition-colors flex items-start gap-2"
          >
            <MapPin className="w-4 h-4 text-earth-400 mt-0.5 shrink-0" />
            <div>
              <div className="text-sm font-medium">{result.name}</div>
              <div className="text-xs text-gray-500 truncate">{result.display_name}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
