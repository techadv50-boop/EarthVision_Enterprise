import { useEffect, useState } from 'react';
import { Loader2, MapPin, Search } from 'lucide-react';
import { gisService, type GeocodeResult } from '../../services/gisService';
import { getErrorMessage } from '../../services/api';
import type { CollectionName } from '../../services/catalogService';
import { satelliteService, type SatellitePublic } from '../../services/satelliteService';
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

export interface SatelliteOption {
  id: string;
  label: string;
  collections: CollectionName[];
}

/** Fallback if the satellites API is unreachable. */
export const SATELLITE_OPTIONS: SatelliteOption[] = [
  { id: 'SENTINEL-2', label: 'Sentinel-2', collections: ['SENTINEL-2'] },
  { id: 'SENTINEL-1', label: 'Sentinel-1', collections: ['SENTINEL-1'] },
  { id: 'SENTINEL-3', label: 'Sentinel-3', collections: ['SENTINEL-3'] },
  { id: 'SENTINEL-5P', label: 'Sentinel-5P', collections: ['SENTINEL-5P'] },
  { id: 'LANDSAT-9', label: 'Landsat-9', collections: ['LANDSAT-9'] },
  { id: 'LANDSAT-8', label: 'Landsat-8', collections: ['LANDSAT-8'] },
  { id: 'LANDSAT-7', label: 'Landsat-7', collections: ['LANDSAT-7'] },
  { id: 'MODIS', label: 'MODIS (Terra+Aqua)', collections: ['TERRAAQUA'] },
  { id: 'TERRA', label: 'Terra MODIS', collections: ['TERRA'] },
  { id: 'AQUA', label: 'Aqua MODIS', collections: ['AQUA'] },
  { id: 'SMOS', label: 'SMOS', collections: ['SMOS'] },
];

export interface CatalogFilters {
  satelliteId: string;
  satelliteLabel: string;
  collections: CollectionName[];
  startDate: string;
  endDate: string;
}

interface Props {
  onSelect: (place: PlaceSelection, filters: CatalogFilters) => void;
  busy?: boolean;
  filters: CatalogFilters;
  onFiltersChange: (filters: CatalogFilters) => void;
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

function toOptions(rows: SatellitePublic[]): SatelliteOption[] {
  return rows.map((row) => ({
    id: row.name,
    label: row.label,
    collections: [row.collection_id],
  }));
}

export function PlaceStep({ onSelect, busy, filters, onFiltersChange }: Props) {
  const [query, setQuery] = useState('Lahore');
  const [results, setResults] = useState<GeocodeResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [satellites, setSatellites] = useState<SatelliteOption[]>(SATELLITE_OPTIONS);
  const [satsLoading, setSatsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setSatsLoading(true);
      try {
        const rows = await satelliteService.listEnabled();
        if (!cancelled && rows.length) {
          setSatellites(toOptions(rows));
        }
      } catch {
        // Keep static fallback
      } finally {
        if (!cancelled) setSatsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const satelliteSelected = Boolean(filters.satelliteId);
  const { startDate, endDate } = filters;
  const rangeError =
    startDate && endDate && startDate > endDate
      ? 'From date must be on or before To date'
      : null;
  const canSearchPlace =
    satelliteSelected && Boolean(startDate) && Boolean(endDate) && !rangeError;

  const pickSatellite = (option: SatelliteOption) => {
    setError(null);
    onFiltersChange({
      ...filters,
      satelliteId: option.id,
      satelliteLabel: option.label,
      collections: option.collections,
    });
  };

  const selectPlace = (place: PlaceSelection) => {
    if (!filters.satelliteId) {
      setError('Select a satellite first');
      return;
    }
    if (rangeError || !startDate || !endDate) {
      setError(rangeError || 'Choose a From and To date for scenes');
      return;
    }
    setError(null);
    onSelect(place, filters);
  };

  const search = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!query.trim()) return;
    if (!canSearchPlace) {
      setError(
        !filters.satelliteId
          ? 'Select a satellite first'
          : rangeError || 'Choose a From and To date for scenes',
      );
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
        <h2 className="font-display text-lg font-semibold text-[var(--ink)]">Find scenes</h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Choose a satellite first, then the date range, then a place.
        </p>
      </div>

      <div className="space-y-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
          1. Satellite
        </div>
        {satsLoading ? (
          <div className="flex items-center gap-2 py-2 text-xs text-[var(--muted)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading satellites…
          </div>
        ) : (
          <div className="grid max-h-56 grid-cols-2 gap-2 overflow-y-auto pr-0.5">
            {satellites.map((option) => {
              const active = filters.satelliteId === option.id;
              return (
                <button
                  key={option.id}
                  type="button"
                  disabled={busy}
                  onClick={() => pickSatellite(option)}
                  className={`rounded-lg border px-3 py-2 text-left text-sm font-medium transition ${
                    active
                      ? 'border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)] ring-1 ring-[var(--accent)]/30'
                      : 'border-[var(--line)] bg-white text-[var(--ink)] hover:bg-[var(--accent-soft)]/50'
                  }`}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {satelliteSelected && (
        <div className="space-y-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
            2. Date range
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
                  onFiltersChange({ ...filters, startDate: e.target.value })
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
                  onFiltersChange({ ...filters, endDate: e.target.value })
                }
                disabled={busy}
                required
              />
            </label>
          </div>
          {rangeError && <p className="text-xs text-red-600">{rangeError}</p>}
        </div>
      )}

      {canSearchPlace && (
        <div className="space-y-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
            3. Place
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
              disabled={loading || busy}
            >
              <Search className="h-4 w-4" />
              {loading ? '…' : 'Search'}
            </button>
          </form>

          <div className="flex flex-wrap gap-2">
            {QUICK_PLACES.map((p) => (
              <button
                key={p.name}
                type="button"
                className="rounded-full border border-[var(--line)] bg-[var(--accent-soft)] px-3 py-1 text-xs font-medium text-[var(--accent)] hover:brightness-95"
                onClick={() => selectPlace(p)}
                disabled={busy}
              >
                {p.name.split(',')[0]}
              </button>
            ))}
          </div>

          <p className="text-[11px] text-[var(--muted)]">
            Or click the map to use that location.
          </p>

          {results.length > 0 && (
            <ul className="max-h-48 space-y-1 overflow-y-auto">
              {results.map((r) => (
                <li key={`${r.longitude}-${r.latitude}-${r.display_name}`}>
                  <button
                    type="button"
                    className="flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left text-sm hover:bg-[var(--accent-soft)]"
                    onClick={() => selectPlace(resultToPlace(r))}
                    disabled={busy}
                  >
                    <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-[var(--accent)]" />
                    <span>{r.display_name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
