import { useMemo, useState } from 'react';
import { CalendarRange, Satellite } from 'lucide-react';
import type { CollectionName } from '../../services/catalogService';
import type { PlaceSelection } from '../../store/workflowStore';

export interface CatalogQuery {
  collection: CollectionName;
  startDate: string; // YYYY-MM-DD
  endDate: string; // YYYY-MM-DD
}

interface Props {
  place: PlaceSelection;
  initial?: CatalogQuery | null;
  busy?: boolean;
  onSearch: (query: CatalogQuery) => void;
  onBack: () => void;
}

const SATELLITES: Array<{
  id: CollectionName;
  label: string;
  blurb: string;
  earliest: string;
}> = [
  {
    id: 'LANDSAT-8',
    label: 'Landsat 8 / heritage',
    blurb: 'True-color optical · archive back to Landsat-5/7 era (≈1984+)',
    earliest: '1984-01-01',
  },
  {
    id: 'LANDSAT-9',
    label: 'Landsat 9',
    blurb: 'True-color optical · 2021–present',
    earliest: '2021-09-01',
  },
  {
    id: 'SENTINEL-2',
    label: 'Sentinel-2',
    blurb: '10 m optical · 2015–present',
    earliest: '2015-06-01',
  },
  {
    id: 'SENTINEL-1',
    label: 'Sentinel-1',
    blurb: 'SAR grayscale · 2014–present (all-weather)',
    earliest: '2014-10-01',
  },
  {
    id: 'MODIS',
    label: 'MODIS',
    blurb: 'Coarse daily optical · 2000–present',
    earliest: '2000-02-01',
  },
];

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function yearAgoIso(): string {
  const d = new Date();
  d.setFullYear(d.getFullYear() - 1);
  return d.toISOString().slice(0, 10);
}

export function CatalogQueryStep({ place, initial, busy, onSearch, onBack }: Props) {
  const [collection, setCollection] = useState<CollectionName>(
    initial?.collection ?? 'SENTINEL-2',
  );
  const [startDate, setStartDate] = useState(initial?.startDate ?? yearAgoIso());
  const [endDate, setEndDate] = useState(initial?.endDate ?? todayIso());
  const [error, setError] = useState<string | null>(null);

  const selectedMeta = useMemo(
    () => SATELLITES.find((s) => s.id === collection) ?? SATELLITES[0],
    [collection],
  );

  const applyPreset = (kind: 'year2000' | 'last12' | 'y2023' | 'mission') => {
    if (kind === 'year2000') {
      setStartDate('2000-01-01');
      setEndDate('2000-12-31');
      if (collection === 'SENTINEL-1' || collection === 'SENTINEL-2' || collection === 'LANDSAT-9') {
        setCollection('LANDSAT-8');
      }
      return;
    }
    if (kind === 'last12') {
      setStartDate(yearAgoIso());
      setEndDate(todayIso());
      return;
    }
    if (kind === 'y2023') {
      setStartDate('2023-01-01');
      setEndDate('2023-12-31');
      return;
    }
    setStartDate(selectedMeta.earliest);
    setEndDate(todayIso());
  };

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!startDate || !endDate) {
      setError('Choose both a start and end date.');
      return;
    }
    if (startDate > endDate) {
      setError('Start date must be on or before end date.');
      return;
    }
    if (endDate < selectedMeta.earliest) {
      setError(
        `${selectedMeta.label} has no imagery before ${selectedMeta.earliest}. Pick a later range or another satellite.`,
      );
      return;
    }
    setError(null);
    onSearch({ collection, startDate, endDate });
  };

  return (
    <div className="space-y-4">
      <div>
        <button
          type="button"
          className="ev-btn-ghost mb-1 -ml-2 px-2 py-1 text-xs"
          onClick={onBack}
          disabled={busy}
        >
          ← Change place
        </button>
        <h2 className="font-display text-lg font-semibold text-[var(--ink)]">
          Choose satellite & dates
        </h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Near <span className="font-medium text-[var(--ink)]">{place.name}</span>
          {' — '}pick one satellite and the date range, then load matching scenes.
        </p>
      </div>

      <form onSubmit={submit} className="space-y-4">
        <fieldset className="space-y-2">
          <legend className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
            <Satellite className="h-3.5 w-3.5" />
            Satellite
          </legend>
          <div className="space-y-1.5">
            {SATELLITES.map((sat) => {
              const active = collection === sat.id;
              return (
                <label
                  key={sat.id}
                  className={`flex cursor-pointer items-start gap-2 rounded-lg border px-2.5 py-2 text-sm ${
                    active
                      ? 'border-[var(--accent)] bg-[var(--accent-soft)]/50'
                      : 'border-[var(--line)] bg-white hover:bg-[var(--accent-soft)]/30'
                  }`}
                >
                  <input
                    type="radio"
                    className="mt-1 accent-[var(--accent)]"
                    name="satellite"
                    checked={active}
                    onChange={() => setCollection(sat.id)}
                    disabled={busy}
                  />
                  <span className="min-w-0">
                    <span className="block font-medium text-[var(--ink)]">{sat.label}</span>
                    <span className="block text-[11px] text-[var(--muted)]">{sat.blurb}</span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>

        <fieldset className="space-y-2">
          <legend className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
            <CalendarRange className="h-3.5 w-3.5" />
            Date range
          </legend>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs text-[var(--muted)]">
              From
              <input
                type="date"
                className="ev-input mt-1"
                value={startDate}
                min={selectedMeta.earliest}
                max={endDate || todayIso()}
                onChange={(e) => setStartDate(e.target.value)}
                disabled={busy}
                required
              />
            </label>
            <label className="text-xs text-[var(--muted)]">
              To
              <input
                type="date"
                className="ev-input mt-1"
                value={endDate}
                min={startDate || selectedMeta.earliest}
                max={todayIso()}
                onChange={(e) => setEndDate(e.target.value)}
                disabled={busy}
                required
              />
            </label>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(
              [
                ['last12', 'Last 12 months'],
                ['y2023', 'Year 2023'],
                ['year2000', 'Year 2000'],
                ['mission', 'Full mission'],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                className="rounded-full border border-[var(--line)] bg-white px-2.5 py-0.5 text-[10px] font-medium text-[var(--accent)] hover:bg-[var(--accent-soft)]"
                onClick={() => applyPreset(id)}
                disabled={busy}
              >
                {label}
              </button>
            ))}
          </div>
        </fieldset>

        {error && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-2.5 py-2 text-xs text-red-700">
            {error}
          </p>
        )}

        <button type="submit" className="ev-btn-primary w-full" disabled={busy}>
          {busy ? 'Loading scenes…' : `Load ${selectedMeta.label} scenes`}
        </button>
      </form>
    </div>
  );
}
