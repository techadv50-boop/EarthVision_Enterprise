import { useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import WatchMap from './WatchMap';
import { loadActiveCatalog, type ActiveSat } from './watch/catalog';
import { scanActive, type WatchHit, type WatchRelation } from './watch/scan';

type Country = 'pak' | 'ind';
type Level = 0 | 1 | 2;

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
  const [country, setCountry] = useState<Country | null>(null);
  const [level, setLevel] = useState<Level | null>(null);
  const [areas, setAreas] = useState<GeoJSON.FeatureCollection | null>(null);
  const [areaName, setAreaName] = useState('');
  const [catalog, setCatalog] = useState<ActiveSat[] | null>(null);
  const [catalogError, setCatalogError] = useState('');
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [hits, setHits] = useState<WatchHit[]>([]);
  const [showInView, setShowInView] = useState(true);
  const [areaError, setAreaError] = useState('');
  const scanId = useRef(0);

  useEffect(() => {
    let cancelled = false;
    setCatalogLoading(true);
    setCatalogError('');
    loadActiveCatalog()
      .then((sats) => {
        if (!cancelled) setCatalog(sats);
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
    if (!country || level == null) {
      setAreas(null);
      return;
    }
    let cancelled = false;
    setAreas(null);
    setAreaError('');
    void fetch(`/aoi/${country}-${level}.geojson`)
      .then((resp) => {
        if (!resp.ok) throw new Error('missing');
        return resp.json();
      })
      .then((data: GeoJSON.FeatureCollection) => {
        if (!cancelled) setAreas(data);
      })
      .catch(() => {
        if (!cancelled) setAreaError('Could not load that area level.');
      });
    return () => {
      cancelled = true;
    };
  }, [country, level]);

  const choose = (nextCountry: Country, nextLevel: Level) => {
    setCountry(nextCountry);
    setLevel(nextLevel);
    setHits([]);
    setAreaName('');
  };

  const inspect = (feature: GeoJSON.Feature) => {
    if (!feature.geometry) return;
    const name = String((feature.properties as { name?: string } | null)?.name || 'Area');
    setAreaName(name);
    const id = ++scanId.current;
    setScanning(true);
    setHits([]);
    setProgress({ done: 0, total: catalog?.length ?? 0 });
    void (async () => {
      try {
        const sats = catalog ?? (await loadActiveCatalog());
        if (id !== scanId.current) return;
        if (!catalog) setCatalog(sats);
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
      } catch {
        if (id === scanId.current) setCatalogError('Could not check satellites over that area.');
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
            <h2 className="text-xs font-semibold uppercase tracking-wide text-cyan-400">Who is watching you</h2>
            <p className="mt-1 text-[11px] leading-relaxed text-gray-400">
              Every satellite Celestrak lists as active is checked. Pick a country level, then click an area.
              The list is who is over that area right now.
            </p>
            <p className="mt-1 text-[11px] text-gray-500">
              {catalogLoading
                ? 'Loading the active catalog…'
                : catalog
                  ? `${catalog.length.toLocaleString()} active satellites loaded.`
                  : 'Active catalog not loaded.'}
            </p>
            {catalogError && <p className="mt-1 text-[11px] text-red-400">{catalogError}</p>}
          </div>

          <div>
            <p className="text-[11px] font-medium text-gray-300">Area levels</p>
            <p className="mt-0.5 text-[10px] text-gray-500">
              Level 0 is the whole country, level 1 provinces, level 2 districts. Pakistan includes Kashmir.
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              {([
                ['pak', 'Pakistan'],
                ['ind', 'India'],
              ] as const).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => choose(id, level ?? 0)}
                  className={`rounded px-2 py-0.5 text-[11px] ring-1 ${
                    country === id
                      ? 'bg-cyan-600 text-white ring-cyan-500'
                      : 'bg-white/5 text-gray-300 ring-white/10 hover:bg-white/10'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="mt-1 flex flex-wrap gap-1">
              {([
                [0, 'Level 0'],
                [1, 'Level 1'],
                [2, 'Level 2'],
              ] as const).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => choose(country ?? 'pak', id)}
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
            {areaError && <p className="mt-1 text-[11px] text-red-400">{areaError}</p>}
          </div>

          {areaName && (
            <div>
              <p className="text-[11px] text-gray-300">
                <span className="text-gray-500">Selected:</span> {areaName}
              </p>
              <p className="mt-0.5 text-[11px] text-gray-400">
                {scanning
                  ? `Checking satellites… ${progress.done.toLocaleString()} / ${progress.total.toLocaleString()}`
                  : `${overhead} over the area · ${watching} with swath on it · ${inView} above the horizon`}
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
                Showing the closest {visible.length} of {matched.length}.
              </p>
            )}
            {!scanning && areaName && visible.length === 0 && (
              <p className="text-[11px] text-gray-500">No active satellite is over that area right now.</p>
            )}
            {!areaName && (
              <p className="text-[11px] text-gray-500">Click a shape on the map to see who is above it.</p>
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
