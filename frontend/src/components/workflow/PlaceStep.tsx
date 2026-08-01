import { useState } from 'react';
import { MapPin, Search } from 'lucide-react';
import { gisService, type GeocodeResult } from '../../services/gisService';
import { getErrorMessage } from '../../services/api';
import type { PlaceSelection } from '../../store/workflowStore';

const QUICK_PLACES: PlaceSelection[] = [
  {
    name: 'Lahore, Pakistan',
    longitude: 74.3587,
    latitude: 31.5204,
    bbox: [74.15, 31.35, 74.55, 31.7],
  },
  {
    name: 'Karachi, Pakistan',
    longitude: 67.0011,
    latitude: 24.8607,
    bbox: [66.85, 24.75, 67.2, 25.0],
  },
  {
    name: 'Islamabad, Pakistan',
    longitude: 73.0479,
    latitude: 33.6844,
    bbox: [72.9, 33.55, 73.2, 33.8],
  },
  {
    name: 'Paris, France',
    longitude: 2.3522,
    latitude: 48.8566,
    bbox: [2.2, 48.8, 2.5, 48.95],
  },
];

export interface SceneDateRange {
  startDate: string; // YYYY-MM-DD
  endDate: string;
}

interface Props {
  onSelect: (place: PlaceSelection, range: SceneDateRange) => void;
  busy?: boolean;
  dateRange: SceneDateRange;
  onDateRangeChange: (range: SceneDateRange) => void;
}

function resultToPlace(r: GeocodeResult): PlaceSelection {
  const bbox = r.bounding_box as [number, number, number, number] | null | undefined;
  if (bbox && bbox.length === 4) {
    return {
      name: r.display_name,
      longitude: r.longitude,
      latitude: r.latitude,
      bbox,
    };
  }
  const pad = 0.2;
  return {
    name: r.display_name,
    longitude: r.longitude,
    latitude: r.latitude,
    bbox: [r.longitude - pad, r.latitude - pad, r.longitude + pad, r.latitude + pad],
  };
}

export function PlaceStep({
  onSelect,
  busy,
  dateRange,
  onDateRangeChange,
}: Props) {
  const [query, setQuery] = useState('Lahore');
  const [results, setResults] = useState<GeocodeResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { startDate, endDate } = dateRange;
  const rangeError =
    startDate && endDate && startDate > endDate
      ? 'From date must be on or before To date'
      : null;

  const selectPlace = (place: PlaceSelection) => {
    if (rangeError || !startDate || !endDate) {
      setError(rangeError || 'Choose a From and To date for scenes');
      return;
    }
    setError(null);
    onSelect(place, { startDate, endDate });
  };

  const search = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!query.trim()) return;
    if (rangeError || !startDate || !endDate) {
      setError(rangeError || 'Choose a From and To date for scenes');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await gisService.geocode(query.trim(), 6);
      setResults(data);
      if (data.length === 1) selectPlace(resultToPlace(data[0]));
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="font-display text-lg font-semibold text-[var(--ink)]">Choose a place</h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Set the date range, then search a city or click the map to load matching scenes.
        </p>
      </div>

      <div className="space-y-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
          Scene date range
        </div>
        <div className="grid grid-cols-2 gap-2">
          <label className="block">
            <span className="mb-1 block text-[11px] text-[var(--muted)]">From</span>
            <input
              type="date"
              className="ev-input text-sm"
              value={startDate}
              max={endDate || undefined}
              onChange={(e) =>
                onDateRangeChange({ startDate: e.target.value, endDate })
              }
              disabled={busy}
              required
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] text-[var(--muted)]">To</span>
            <input
              type="date"
              className="ev-input text-sm"
              value={endDate}
              min={startDate || undefined}
              onChange={(e) =>
                onDateRangeChange({ startDate, endDate: e.target.value })
              }
              disabled={busy}
              required
            />
          </label>
        </div>
        {rangeError && <p className="text-xs text-red-600">{rangeError}</p>}
      </div>

      <form onSubmit={search} className="flex gap-2">
        <input
          className="ev-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. Lahore"
          disabled={busy}
        />
        <button
          type="submit"
          className="ev-btn-primary shrink-0"
          disabled={loading || busy || Boolean(rangeError)}
        >
          <Search className="h-4 w-4" />
          {loading ? '…' : 'Search'}
        </button>
      </form>

      {error && <p className="text-xs text-red-600">{error}</p>}

      <div className="flex flex-wrap gap-2">
        {QUICK_PLACES.map((p) => (
          <button
            key={p.name}
            type="button"
            className="rounded-full border border-[var(--line)] bg-[var(--accent-soft)] px-3 py-1 text-xs font-medium text-[var(--accent)] hover:brightness-95"
            onClick={() => selectPlace(p)}
            disabled={busy || Boolean(rangeError)}
          >
            {p.name.split(',')[0]}
          </button>
        ))}
      </div>

      {results.length > 0 && (
        <ul className="max-h-48 space-y-1 overflow-y-auto">
          {results.map((r) => (
            <li key={`${r.longitude}-${r.latitude}-${r.display_name}`}>
              <button
                type="button"
                className="flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left text-sm hover:bg-[var(--accent-soft)]"
                onClick={() => selectPlace(resultToPlace(r))}
                disabled={busy || Boolean(rangeError)}
              >
                <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-[var(--accent)]" />
                <span>{r.display_name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
