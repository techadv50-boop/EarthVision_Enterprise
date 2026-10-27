import { useEffect, useMemo, useRef, useState } from 'react';
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

interface AreaProps {
  name?: string;
  country?: string;
  level?: number;
}

interface CountryLink {
  province: string | null;
  district: string | null;
}

function areaProps(feature: GeoJSON.Feature): { name: string; country: string; level: number } {
  const props = (feature.properties || {}) as AreaProps;
  return {
    name: String(props.name || ''),
    country: String(props.country || ''),
    level: Number(props.level || 0),
  };
}

function collection(features: GeoJSON.Feature[]): GeoJSON.FeatureCollection {
  return { type: 'FeatureCollection', features };
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
  const [countries, setCountries] = useState<GeoJSON.FeatureCollection | null>(null);
  const [countryIndex, setCountryIndex] = useState<Record<string, CountryLink> | null>(null);
  const [provinces, setProvinces] = useState<GeoJSON.FeatureCollection | null>(null);
  const [districts, setDistricts] = useState<GeoJSON.FeatureCollection | null>(null);
  const [countryName, setCountryName] = useState('');
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
    setAreaError('');
    void Promise.all([
      fetch(BOUNDARY_URL[1]).then((resp) => {
        if (!resp.ok) throw new Error('missing');
        return resp.json() as Promise<GeoJSON.FeatureCollection>;
      }),
      fetch('/boundaries/country-index.json').then((resp) => {
        if (!resp.ok) throw new Error('missing');
        return resp.json() as Promise<Record<string, CountryLink>>;
      }),
    ])
      .then(([data, index]) => {
        if (cancelled) return;
        setCountries(worldBoundaries(data));
        setCountryIndex(index);
      })
      .catch(() => {
        if (!cancelled) setAreaError('Could not load country boundaries.');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (level < 2 || provinces) return;
    let cancelled = false;
    void fetch(BOUNDARY_URL[2])
      .then((resp) => {
        if (!resp.ok) throw new Error('missing');
        return resp.json() as Promise<GeoJSON.FeatureCollection>;
      })
      .then((data) => {
        if (!cancelled) setProvinces(data);
      })
      .catch(() => {
        if (!cancelled) setAreaError('Could not load province boundaries.');
      });
    return () => {
      cancelled = true;
    };
  }, [level, provinces]);

  useEffect(() => {
    if (level < 3 || districts) return;
    let cancelled = false;
    void fetch(BOUNDARY_URL[3])
      .then((resp) => {
        if (!resp.ok) throw new Error('missing');
        return resp.json() as Promise<GeoJSON.FeatureCollection>;
      })
      .then((data) => {
        if (!cancelled) setDistricts(data);
      })
      .catch(() => {
        if (!cancelled) setAreaError('Could not load district boundaries.');
      });
    return () => {
      cancelled = true;
    };
  }, [level, districts]);

  const subAreas = useMemo(() => {
    if (level === 1 || !countryName || !countryIndex) return null;
    const link = countryIndex[countryName];
    const source = level === 2 ? provinces : districts;
    const key = level === 2 ? link?.province : link?.district;
    if (!source || !key) return null;
    return source.features
      .filter((feature) => areaProps(feature).country === key)
      .slice()
      .sort((a, b) => areaProps(a).name.localeCompare(areaProps(b).name));
  }, [level, countryName, countryIndex, provinces, districts]);

  const showingWorld = level === 1 || !countryName;
  const boundariesLoading =
    !countries || (level === 2 && !!countryName && !provinces) || (level === 3 && !!countryName && !districts);

  const mapAreas = useMemo(() => {
    if (!countries) return null;
    if (showingWorld) return countries;
    if ((level === 2 && !provinces) || (level === 3 && !districts)) return null;
    if (!subAreas || subAreas.length === 0) {
      const country = countries.features.find((feature) => areaProps(feature).name === countryName);
      return country ? collection([country]) : collection([]);
    }
    return collection(subAreas);
  }, [countries, showingWorld, subAreas, countryName, level, provinces, districts]);

  const choose = (nextLevel: BoundaryLevel) => {
    setHits([]);
    setCheckedAt(null);
    setAreaName('');
    if (level === 1 && areaName) setCountryName(areaName);
    setLevel(nextLevel);
  };

  const pickCountry = (name: string) => {
    setHits([]);
    setCheckedAt(null);
    setAreaName('');
    setCountryName(name);
    if (level === 1 && name && countries) {
      const feature = countries.features.find((item) => areaProps(item).name === name);
      if (feature) inspect(feature);
    }
  };

  const pickSubArea = (name: string) => {
    const feature = subAreas?.find((item) => areaProps(item).name === name);
    if (feature) inspect(feature);
  };

  const onMapArea = (feature: GeoJSON.Feature) => {
    if (level !== 1 && !countryName) {
      pickCountry(areaProps(feature).name);
      return;
    }
    inspect(feature);
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
              Pick a country from the list, the same way on every level. Level 1 uses the country outline. Level 2
              then lists that country’s provinces. Level 3 lists its districts or divisions. Pakistan includes Kashmir.
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
            {countries && countries.features.length > 0 && (
              <label className="mt-2 block text-[11px] text-gray-400">
                Country
                <select
                  value={level === 1 ? areaName : countryName}
                  onChange={(event) => pickCountry(event.target.value)}
                  className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm text-gray-100 outline-none ring-1 ring-white/10"
                >
                  <option value="">Choose a country</option>
                  {countries.features.map((feature) => {
                    const name = areaProps(feature).name;
                    return (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    );
                  })}
                </select>
              </label>
            )}
            {level !== 1 && countryName && subAreas && subAreas.length > 0 && (
              <label className="mt-2 block text-[11px] text-gray-400">
                {level === 2 ? 'Province' : 'District or division'}
                <select
                  value={areaName}
                  onChange={(event) => pickSubArea(event.target.value)}
                  className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm text-gray-100 outline-none ring-1 ring-white/10"
                >
                  <option value="">{level === 2 ? 'Choose a province' : 'Choose a district'}</option>
                  {subAreas.map((feature, index) => {
                    const name = areaProps(feature).name;
                    return (
                      <option key={`${name}-${index}`} value={name}>
                        {name}
                      </option>
                    );
                  })}
                </select>
              </label>
            )}
            {level !== 1 && countryName && !boundariesLoading && (!subAreas || subAreas.length === 0) && (
              <p className="mt-1 text-[11px] text-gray-500">
                {countryName} is shown with its country outline.
              </p>
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
                {showingWorld
                  ? 'Choose a country from the list, or click one on the map.'
                  : subAreas && subAreas.length > 0
                    ? `${subAreas.length.toLocaleString()} ${level === 2 ? 'provinces' : 'districts'} of ${countryName} are on the map. Choose one from the list, or click it.`
                    : boundariesLoading
                      ? 'Loading boundaries…'
                      : `The outline of ${countryName} is on the map.`}
              </p>
            )}
          </div>
        </div>
      </aside>
      <div className="relative z-0 min-h-0 flex-1">
        {(catalogLoading || scanning || boundariesLoading) && (
          <div className="pointer-events-none absolute left-3 top-3 z-[1000] inline-flex items-center gap-2 rounded bg-gray-950/90 px-2 py-1 text-[11px] text-cyan-200 ring-1 ring-white/10">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {catalogLoading ? 'Loading active satellites' : boundariesLoading ? 'Loading boundaries' : 'Checking who is overhead'}
          </div>
        )}
        <WatchMap adminGeojson={mapAreas} selectedName={areaName || null} hits={visible} onArea={onMapArea} />
      </div>
    </div>
  );
}
