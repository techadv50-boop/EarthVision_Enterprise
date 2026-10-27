import { useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import WatchMap from './WatchMap';
import { catalogSourceNote, loadActiveCatalog, satelliteType, type ActiveSat } from './watch/catalog';
import { exportOverheadCsv } from './watch/export';
import { scanActive, type WatchHit, type WatchRelation } from './watch/scan';

type BoundaryLevel = 1 | 2 | 3;

const BOUNDARY_URL: Record<BoundaryLevel, string> = {
  1: '/world-countries-110m.geojson',
  2: '/boundaries/world-provinces.geojson',
  3: '/boundaries/world-districts.geojson',
};

interface WorldProps {
  NAME?: string;
}

function worldBoundaries(data: GeoJSON.FeatureCollection): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: data.features
      .filter((feature) => feature.geometry)
      .map((feature) => {
        const name = String((feature.properties as WorldProps | null)?.NAME || 'Area');
        return {
          type: 'Feature' as const,
          properties: { name, country: name, level: 0 },
          geometry: feature.geometry,
        };
      })
      .sort((a, b) => String(a.properties.name).localeCompare(String(b.properties.name))),
  };
}

const RELATION_LABEL: Record<WatchRelation, string> = {
  overhead: 'Over the area',
  watching: 'Swath covers the area',
  'in-view': 'Above the horizon',
};

export default function WatchView({
  onTrack,
}: {
  onTrack?: (name: string, line1: string, line2: string, noradId: number | null) => void;
}) {
  const [level, setLevel] = useState<BoundaryLevel>(1);
  const [placeQuery, setPlaceQuery] = useState('');
  const [areas, setAreas] = useState<GeoJSON.FeatureCollection | null>(null);
  const [areaName, setAreaName] = useState('');
  const [catalog, setCatalog] = useState<ActiveSat[] | null>(null);
  const [catalogNote, setCatalogNote] = useState('');
  const [catalogError, setCatalogError] = useState('');
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [hits, setHits] = useState<WatchHit[]>([]);
  const [showInView, setShowInView] = useState(true);
  const [areaError, setAreaError] = useState('');
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const scanId = useRef(0);

  useEffect(() => {
    let cancelled = false;
    setCatalogLoading(true);
    setCatalogError('');
    loadActiveCatalog()
      .then((sats) => {
        if (!cancelled) {
          setCatalog(sats);
          setCatalogNote(catalogSourceNote());
          setCatalogError('');
        }
      })
      .catch(() => {
        if (!cancelled) setCatalogError('Could not load the live catalog of active satellites.');
      })
      .finally(() => {
        if (!cancelled) setCatalogLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setAreas(null);
    setAreaError('');
    void fetch(BOUNDARY_URL[level])
      .then((resp) => {
        if (!resp.ok) throw new Error('missing');
        return resp.json();
      })
      .then((data: GeoJSON.FeatureCollection) => {
        if (cancelled) return;
        setAreas(level === 1 ? worldBoundaries(data) : data);
      })
      .catch(() => {
        if (!cancelled) setAreaError('Could not load those boundaries.');
      });
    return () => {
      cancelled = true;
    };
  }, [level]);

  const choose = (nextLevel: BoundaryLevel) => {
    setLevel(nextLevel);
    setHits([]);
    setAreaName('');
    setCheckedAt(null);
    setPlaceQuery('');
  };

  const findPlace = (query: string) => {
    const q = query.trim().toLowerCase();
    if (!q || !areas) return;
    const named = areas.features.map((feature) => ({
      feature,
      name: String((feature.properties as { name?: string } | null)?.name || ''),
    }));
    const exact = named.find((item) => item.name.toLowerCase() === q);
    const partial = named.find((item) => item.name.toLowerCase().includes(q));
    const hit = exact || partial;
    if (hit) inspect(hit.feature);
  };

  const inspect = (feature: GeoJSON.Feature) => {
    if (!feature.geometry) return;
    const name = String((feature.properties as { name?: string } | null)?.name || 'Area');
    setAreaName(name);
    const id = ++scanId.current;
    setScanning(true);
    setCatalogError('');
    setHits([]);
    setCheckedAt(null);
    setProgress({ done: 0, total: catalog?.length ?? 0 });
    void (async () => {
      try {
        const sats = catalog ?? (await loadActiveCatalog());
        if (id !== scanId.current) return;
        if (!catalog) {
          setCatalog(sats);
          setCatalogNote(catalogSourceNote());
        }
        const found = await scanActive(
          sats,
          feature.geometry as GeoJSON.Geometry,
          new Date(),
          (done, total, partial) => {
            if (id !== scanId.current) return;
            setProgress({ done, total });
            setHits(partial.slice());
          },
          () => id !== scanId.current,
        );
        if (id !== scanId.current) return;
        setHits(found);
        setCheckedAt(new Date());
        setCatalogError('');
      } catch (err) {
        if (id === scanId.current) {
          const detail = err instanceof Error && err.message ? ` ${err.message}` : '';
          setCatalogError(`Could not check satellites over that area.${detail}`);
        }
      } finally {
        if (id === scanId.current) setScanning(false);
      }
    })();
  };

  const matched = showInView ? hits : hits.filter((hit) => hit.relation !== 'in-view');
  const visible = matched.slice(0, 250);
  const overhead = hits.filter((hit) => hit.relation === 'overhead').length;
  const watching = hits.filter((hit) => hit.relation === 'watching').length;
  const inView = hits.filter((hit) => hit.relation === 'in-view').length;

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden">
      <aside className="flex h-full w-[380px] max-w-[92vw] shrink-0 flex-col border-r border-white/10 bg-gray-950">
        <div className="space-y-3 overflow-y-auto px-4 py-4">
          <div>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-cyan-400">Who is overhead</h2>
            <p className="mt-1 text-[11px] leading-relaxed text-gray-400">
              The catalog is every satellite Celestrak lists as active. Click a country, province, or district.
              The list below is only the satellites over that shape, not the whole catalog.
            </p>
            <p className="mt-1 text-[11px] text-gray-500">
              {catalogLoading
                ? 'Loading the active catalog…'
                : catalog
                  ? `Catalog: ${catalog.length.toLocaleString()} active satellites.`
                  : 'Active catalog not loaded.'}
            </p>
            {catalogNote && <p className="mt-1 text-[11px] text-gray-500">{catalogNote}</p>}
            {catalogError && <p className="mt-1 text-[11px] text-red-400">{catalogError}</p>}
          </div>

          <div>
            <p className="text-[11px] font-medium text-gray-300">Boundaries</p>
            <p className="mt-0.5 text-[10px] text-gray-500">
              Level 1 is the country, the same outlines as now. Level 2 is the province. Level 3 is the district or
              division. Pakistan includes Kashmir. Province and district outlines use Natural Earth and geoBoundaries.
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              {([
                [1, 'Level 1'],
                [2, 'Level 2'],
                [3, 'Level 3'],
              ] as const).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => choose(id)}
                  className={`rounded px-2 py-0.5 text-[11px] ring-1 ${
                    level === id
                      ? 'bg-cyan-600 text-white ring-cyan-500'
                      : 'bg-white/5 text-gray-300 ring-white/10 hover:bg-white/10'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {level === 1 && areas && areas.features.length > 0 && (
              <label className="mt-2 block text-[11px] text-gray-400">
                Country
                <select
                  value={areaName}
                  onChange={(event) => findPlace(event.target.value)}
                  className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm text-gray-100 outline-none ring-1 ring-white/10"
                >
                  <option value="">Choose a country</option>
                  {areas.features.map((feature) => {
                    const name = String((feature.properties as { name?: string } | null)?.name || '');
                    return (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    );
                  })}
                </select>
              </label>
            )}
            {level !== 1 && (
              <label className="mt-2 block text-[11px] text-gray-400">
                {level === 2 ? 'Province' : 'District'}
                <input
                  value={placeQuery}
                  onChange={(event) => setPlaceQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') findPlace(placeQuery);
                  }}
                  placeholder={level === 2 ? 'Type a province and press Enter' : 'Type a district and press Enter'}
                  className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm text-gray-100 outline-none ring-1 ring-white/10"
                />
              </label>
            )}
            {areaError && <p className="mt-1 text-[11px] text-red-400">{areaError}</p>}
          </div>

          {areaName && (
            <div>
              <p className="text-[11px] text-gray-300">
                <span className="text-gray-500">Selected:</span> {areaName}
              </p>
              <p className="mt-0.5 text-[11px] text-gray-400">
                {scanning
                  ? `Checking the catalog… ${progress.done.toLocaleString()} / ${progress.total.toLocaleString()}`
                  : catalog
                    ? `${overhead.toLocaleString()} of ${catalog.length.toLocaleString()} are over this shape · ${watching.toLocaleString()} with swath on it · ${inView.toLocaleString()} above the horizon`
                    : `${overhead.toLocaleString()} over this shape · ${watching.toLocaleString()} with swath on it · ${inView.toLocaleString()} above the horizon`}
              </p>
              <label className="mt-1 flex items-center gap-1.5 text-[11px] text-gray-400">
                <input
                  type="checkbox"
                  checked={showInView}
                  onChange={() => setShowInView((v) => !v)}
                  className="accent-cyan-500"
                />
                Include satellites that are only above the horizon
              </label>
              <button
                type="button"
                disabled={scanning || matched.length === 0}
                onClick={() => exportOverheadCsv(areaName, matched, checkedAt ?? new Date())}
                className="mt-2 rounded bg-cyan-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-cyan-500 disabled:opacity-40"
              >
                Export list{matched.length > 0 ? ` (${matched.length.toLocaleString()})` : ''}
              </button>
              <p className="mt-1 text-[10px] text-gray-500">
                CSV with name, location, swath, and type (optical, SAR, communication, and others).
                {matched.length > visible.length ? ' The file includes every match, not only the rows on screen.' : ''}
              </p>
            </div>
          )}

          <div className="space-y-1.5">
            {visible.map((hit) => (
              <div
                key={`${hit.noradId ?? hit.name}-${hit.line1.slice(2, 7)}`}
                className="rounded bg-gray-900/70 p-2 ring-1 ring-white/10"
              >
                <div className="flex items-start gap-2">
                  <span
                    className="mt-1 h-2 w-2 shrink-0 rounded-full"
                    style={{
                      background:
                        hit.relation === 'overhead' ? '#fbbf24' : hit.relation === 'watching' ? '#22d3ee' : '#94a3b8',
                    }}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{hit.name}</div>
                    <div className="text-[10px] text-gray-500">
                      {hit.constellation}
                      {` · ${satelliteType(hit.name)}`}
                      {hit.noradId != null ? ` · ${hit.noradId}` : ''}
                      {hit.swathKm != null ? ` · ${hit.swathKm} km swath` : ''}
                    </div>
                    <div className="mt-0.5 text-[10px] text-gray-400">
                      {RELATION_LABEL[hit.relation]} · {hit.altKm.toFixed(0)} km · el {hit.elevationDeg.toFixed(0)}° ·{' '}
                      {hit.distanceKm < 1 ? 'over the shape' : `${hit.distanceKm.toFixed(0)} km from the area`}
                    </div>
                  </div>
                  {onTrack && (
                    <button
                      type="button"
                      onClick={() => onTrack(hit.name, hit.line1, hit.line2, hit.noradId)}
                      className="shrink-0 rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-cyan-300 ring-1 ring-cyan-500/40 hover:bg-white/10"
                    >
                      Track
                    </button>
                  )}
                </div>
              </div>
            ))}
            {matched.length > visible.length && (
              <p className="text-[11px] text-gray-500">
                Showing the closest {visible.length.toLocaleString()} of {matched.length.toLocaleString()} satellites over this shape.
              </p>
            )}
            {!scanning && areaName && matched.length > 0 && matched.length <= visible.length && (
              <p className="text-[11px] text-gray-500">
                This list is {matched.length.toLocaleString()} satellite{matched.length === 1 ? '' : 's'} over {areaName}.
              </p>
            )}
            {!scanning && areaName && visible.length === 0 && (
              <p className="text-[11px] text-gray-500">
                None of the {catalog ? catalog.length.toLocaleString() : 'active'} satellites are over {areaName} right now.
              </p>
            )}
            {!areaName && (
              <p className="text-[11px] text-gray-500">
                Click a boundary on the map.
                {areas
                  ? ` ${areas.features.length.toLocaleString()} ${level === 1 ? 'countries' : level === 2 ? 'provinces' : 'districts'} are drawn.`
                  : ''}
              </p>
            )}
          </div>
        </div>
      </aside>
      <div className="relative z-0 min-h-0 flex-1">
        {(catalogLoading || scanning) && (
          <div className="pointer-events-none absolute left-3 top-3 z-[1000] inline-flex items-center gap-2 rounded bg-gray-950/90 px-2 py-1 text-[11px] text-cyan-200 ring-1 ring-white/10">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {catalogLoading ? 'Loading active satellites' : 'Checking who is overhead'}
          </div>
        )}
        <WatchMap adminGeojson={areas} selectedName={areaName || null} hits={visible} onArea={inspect} />
      </div>
    </div>
  );
}
