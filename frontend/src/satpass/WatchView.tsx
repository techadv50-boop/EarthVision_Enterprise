import { useEffect, useMemo, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import WatchMap, { type WatchLayer, type WatchTrackLine, type WatchTrackMotion } from './WatchMap';
import { compassPoint, getState, groundTrack, parseTle } from './orbit';
import { bearingDeg } from './predict/footprint';
import { catalogSourceNote, loadActiveCatalog, satelliteType, type ActiveSat } from './watch/catalog';
import { exportOverheadCsv } from './watch/export';
import { scanActive, type WatchHit, type WatchRelation } from './watch/scan';

type BoundaryLevel = 1 | 2 | 3;

interface CountryPack {
  provinces?: GeoJSON.Feature[];
  districts?: GeoJSON.Feature[];
}

async function loadFeatures(url: string): Promise<GeoJSON.Feature[]> {
  const resp = await fetch(url);
  if (!resp.ok) return [];
  const data = (await resp.json()) as GeoJSON.Feature[];
  return Array.isArray(data) ? data : [];
}

interface WorldProps {
  NAME?: string;
}

interface AreaProps {
  name?: string;
  country?: string;
  level?: number;
  province?: string;
}

function areaProps(feature: GeoJSON.Feature): { name: string; country: string; level: number; province: string } {
  const props = (feature.properties || {}) as AreaProps;
  return {
    name: String(props.name || ''),
    country: String(props.country || ''),
    level: Number(props.level || 0),
    province: String(props.province || ''),
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

const TRACK_COLORS = ['#fbbf24', '#fb7185', '#a3e635', '#c084fc', '#22d3ee', '#f472b6'];

interface TrackPick {
  key: string;
  name: string;
  line1: string;
  line2: string;
}

function satKey(hit: { noradId: number | null; line1: string }): string {
  return hit.noradId != null ? `n${hit.noradId}` : hit.line1;
}

const RELATION_LABEL: Record<WatchRelation, string> = {
  overhead: 'Over the area',
  watching: 'Swath covers the area',
  'in-view': 'Above the horizon',
};

export default function WatchView() {
  const [level, setLevel] = useState<BoundaryLevel>(1);
  const [countries, setCountries] = useState<GeoJSON.FeatureCollection | null>(null);
  const [packs, setPacks] = useState<Record<string, CountryPack>>({});
  const packsRef = useRef(packs);
  packsRef.current = packs;
  const [countryName, setCountryName] = useState('');
  const [provinceName, setProvinceName] = useState('');
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
  const [tracks, setTracks] = useState<TrackPick[]>([]);
  const [trackMotion, setTrackMotion] = useState<Record<string, WatchTrackMotion>>({});
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
    void fetch('/world-countries-110m.geojson')
      .then((resp) => {
        if (!resp.ok) throw new Error('missing');
        return resp.json() as Promise<GeoJSON.FeatureCollection>;
      })
      .then((data) => {
        if (cancelled) return;
        setCountries(worldBoundaries(data));
      })
      .catch(() => {
        if (!cancelled) setAreaError('Could not load country boundaries.');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (level < 2 || !countryName) return;
    const current = packsRef.current[countryName];
    const needProvinces = !current?.provinces;
    const needDistricts = level === 3 && !current?.districts;
    if (!needProvinces && !needDistricts) return;
    let cancelled = false;
    const file = encodeURIComponent(countryName);
    void (async () => {
      try {
        const [provinces, districts] = await Promise.all([
          needProvinces ? loadFeatures(`/boundaries/provinces/${file}.json`) : Promise.resolve(current?.provinces || []),
          needDistricts ? loadFeatures(`/boundaries/districts/${file}.json`) : Promise.resolve(current?.districts),
        ]);
        if (cancelled) return;
        setPacks((prev) => ({
          ...prev,
          [countryName]: {
            provinces,
            districts: needDistricts ? districts : prev[countryName]?.districts,
          },
        }));
        setAreaError('');
      } catch {
        if (!cancelled) setAreaError('Could not load those boundaries.');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [level, countryName]);

  const countryProvinces = useMemo(() => packs[countryName]?.provinces || [], [packs, countryName]);

  const provinceDistricts = useMemo(() => {
    const list = packs[countryName]?.districts;
    if (level !== 3 || !provinceName || !list) return [];
    return list.filter((feature) => areaProps(feature).province === provinceName);
  }, [level, countryName, provinceName, packs]);

  const showingWorld = level === 1 || !countryName;
  const pack = countryName ? packs[countryName] : undefined;
  const boundariesLoading =
    !countries ||
    (level >= 2 && !!countryName && !pack?.provinces) ||
    (level === 3 && !!provinceName && !pack?.districts);

  const layers = useMemo((): WatchLayer[] => {
    if (!countries) return [];
    if (level === 1) return [{ role: 'select', data: countries }];
    if (level === 2) {
      if (!countryName) return [{ role: 'select', data: countries }];
      if (!pack?.provinces) return [];
      if (countryProvinces.length) return [{ role: 'select', data: collection(countryProvinces) }];
      const country = countries.features.find((feature) => areaProps(feature).name === countryName);
      return country ? [{ role: 'select', data: collection([country]) }] : [];
    }
    const guides: WatchLayer[] = [];
    if (!countryName) return [{ role: 'guide-country', data: countries }];
    const country = countries.features.find((feature) => areaProps(feature).name === countryName);
    if (country) guides.push({ role: 'guide-country', data: collection([country]) });
    if (countryProvinces.length) guides.push({ role: 'guide-province', data: collection(countryProvinces) });
    if (provinceName && pack?.districts && provinceDistricts.length) {
      guides.push({ role: 'select', data: collection(provinceDistricts) });
    }
    return guides;
  }, [countries, level, countryName, pack, countryProvinces, provinceName, provinceDistricts]);

  const choose = (nextLevel: BoundaryLevel) => {
    setHits([]);
    setCheckedAt(null);
    setAreaName('');
    setProvinceName('');
    if (level === 1 && areaName) setCountryName(areaName);
    setLevel(nextLevel);
  };

  const clearSelection = () => {
    scanId.current += 1;
    setScanning(false);
    setHits([]);
    setCheckedAt(null);
    setAreaName('');
    setProvinceName('');
    setCountryName('');
    setTracks([]);
    setTrackMotion({});
  };

  const toggleTrack = (hit: WatchHit) => {
    const key = satKey(hit);
    setTracks((prev) =>
      prev.some((item) => item.key === key)
        ? prev.filter((item) => item.key !== key)
        : [...prev, { key, name: hit.name, line1: hit.line1, line2: hit.line2 }],
    );
  };

  const trackLines = useMemo((): WatchTrackLine[] => {
    return tracks.flatMap((track, index) => {
      try {
        const satrec = parseTle(track.line1, track.line2);
        return [
          {
            key: track.key,
            name: track.name,
            color: TRACK_COLORS[index % TRACK_COLORS.length],
            segments: groundTrack(satrec, new Date()),
          },
        ];
      } catch {
        return [];
      }
    });
  }, [tracks]);

  useEffect(() => {
    if (!tracks.length) {
      setTrackMotion({});
      return;
    }
    const tick = () => {
      const now = new Date();
      const next: Record<string, WatchTrackMotion> = {};
      tracks.forEach((track, index) => {
        try {
          const satrec = parseTle(track.line1, track.line2);
          const state = getState(satrec, now);
          if (!state) return;
          const ahead = getState(satrec, new Date(now.getTime() + 20_000));
          next[track.key] = {
            key: track.key,
            name: track.name,
            color: TRACK_COLORS[index % TRACK_COLORS.length],
            lat: state.lat,
            lon: state.lon,
            altKm: state.altKm,
            speedKmS: state.speedKmS,
            headingDeg: ahead ? bearingDeg(state.lat, state.lon, ahead.lat, ahead.lon) : null,
          };
        } catch {
          /* a bad TLE stays off the map */
        }
      });
      setTrackMotion(next);
    };
    tick();
    const timer = window.setInterval(tick, 2000);
    return () => window.clearInterval(timer);
  }, [tracks]);

  const pickCountry = (name: string) => {
    if (!name) {
      clearSelection();
      return;
    }
    setHits([]);
    setCheckedAt(null);
    setAreaName('');
    setProvinceName('');
    setCountryName(name);
    if (level === 1 && countries) {
      const feature = countries.features.find((item) => areaProps(item).name === name);
      if (feature) inspect(feature);
    }
  };

  const pickProvince = (name: string) => {
    setHits([]);
    setCheckedAt(null);
    setAreaName('');
    setProvinceName(name);
    if (level === 2 && name) {
      const feature = countryProvinces.find((item) => areaProps(item).name === name);
      if (feature) inspect(feature);
    }
  };

  const pickDistrict = (name: string) => {
    const feature = provinceDistricts.find((item) => areaProps(item).name === name);
    if (feature) inspect(feature);
  };

  const onMapArea = (feature: GeoJSON.Feature) => {
    const props = areaProps(feature);
    if (level === 3) {
      if (props.level === 3) inspect(feature);
      else if (props.level === 2) pickProvince(props.name);
      else if (!provinceName) pickCountry(props.name);
      return;
    }
    if (!countryName && level !== 1) {
      pickCountry(props.name);
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
            <div className="flex items-center justify-between gap-2">
              <p className="text-[11px] font-medium text-gray-300">Boundaries</p>
              {(areaName || countryName || provinceName) && (
                <button
                  type="button"
                  onClick={clearSelection}
                  className="rounded bg-white/5 px-2 py-0.5 text-[11px] text-gray-200 ring-1 ring-white/15 hover:bg-white/10"
                >
                  Clear selection
                </button>
              )}
            </div>
            <p className="mt-0.5 text-[10px] text-gray-500">
              Level 1 lists countries. Level 2 lists the provinces of the country you pick. Level 3 draws that country
              and its provinces so you can see them, then lists the districts of the province you pick. Pakistan
              includes Kashmir.
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
            {level !== 1 && countryName && countryProvinces.length > 0 && (
              <label className="mt-2 block text-[11px] text-gray-400">
                Province
                <select
                  value={level === 2 ? areaName : provinceName}
                  onChange={(event) => pickProvince(event.target.value)}
                  className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm text-gray-100 outline-none ring-1 ring-white/10"
                >
                  <option value="">Choose a province</option>
                  {countryProvinces.map((feature, index) => {
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
            {level === 3 && provinceName && provinceDistricts.length > 0 && (
              <label className="mt-2 block text-[11px] text-gray-400">
                District or division
                <select
                  value={areaName}
                  onChange={(event) => pickDistrict(event.target.value)}
                  className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm text-gray-100 outline-none ring-1 ring-white/10"
                >
                  <option value="">Choose a district</option>
                  {provinceDistricts.map((feature, index) => {
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
            {level === 3 && countryName && !boundariesLoading && countryProvinces.length === 0 && (
              <p className="mt-1 text-[11px] text-gray-500">{countryName} is shown with its country outline.</p>
            )}
            {areaError && <p className="mt-1 text-[11px] text-red-400">{areaError}</p>}
          </div>

          {areaName && (
            <div>
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] text-gray-300">
                  <span className="text-gray-500">Selected:</span> {areaName}
                </p>
                <button
                  type="button"
                  onClick={clearSelection}
                  className="shrink-0 rounded bg-white/5 px-2 py-0.5 text-[11px] text-gray-200 ring-1 ring-white/15 hover:bg-white/10"
                >
                  Clear selection
                </button>
              </div>
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
            {visible.map((hit) => {
              const motion = trackMotion[satKey(hit)];
              const heading = motion?.headingDeg;
              return (
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
                    {motion && (
                      <div className="mt-0.5 text-[10px] text-cyan-200">
                        {motion.speedKmS.toFixed(2)} km/s · heading{' '}
                        {heading == null ? '—' : `${Math.round(heading)}° ${compassPoint(heading)}`}
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => toggleTrack(hit)}
                    className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ring-1 ${
                      tracks.some((item) => item.key === satKey(hit))
                        ? 'bg-cyan-600 text-white ring-cyan-500'
                        : 'bg-white/5 text-cyan-300 ring-cyan-500/40 hover:bg-white/10'
                    }`}
                  >
                    {tracks.some((item) => item.key === satKey(hit)) ? 'Track off' : 'Track'}
                  </button>
                </div>
              </div>
              );
            })}
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
                {level === 3 && !countryName
                  ? 'Choose a country. Its provinces are drawn so you can see them. Satellites are listed after you choose a district.'
                  : level === 3 && !provinceName
                    ? countryProvinces.length > 0
                      ? `${countryProvinces.length.toLocaleString()} provinces of ${countryName} are drawn. Choose a province, then a district.`
                      : boundariesLoading
                        ? 'Loading boundaries…'
                        : `The outline of ${countryName} is on the map.`
                    : level === 3
                      ? provinceDistricts.length > 0
                        ? `${provinceDistricts.length.toLocaleString()} districts of ${provinceName} are drawn. Choose one from the list.`
                        : boundariesLoading
                          ? 'Loading boundaries…'
                          : `No districts are drawn for ${provinceName}.`
                      : showingWorld
                        ? 'Choose a country from the list, or click one on the map.'
                        : countryProvinces.length > 0
                          ? `${countryProvinces.length.toLocaleString()} provinces of ${countryName} are on the map. Choose one from the list, or click it.`
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
        <WatchMap
          layers={layers}
          selectedName={areaName || null}
          guideName={level === 3 ? provinceName || null : null}
          hits={visible}
          onArea={onMapArea}
          trackLines={trackLines}
          trackMotion={Object.values(trackMotion)}
        />
      </div>
    </div>
  );
}
