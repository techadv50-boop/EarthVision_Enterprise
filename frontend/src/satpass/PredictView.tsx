import { useMemo, useState } from 'react';
import {
  Plus,
  Trash2,
  Loader2,
  Upload,
  MapPin,
  Calculator,
  Pentagon,
} from 'lucide-react';
import { geoApi, satelliteApi, type TleResult } from '@/services/api';
import type { TrackedSat } from './SatPassMap';
import PredictMap, { type AoiDrawMode } from './PredictMap';
import PredictReport from './PredictReport';
import { colorForSatellite, describeSensor, inferSatelliteKind, noradFromLine1, knownSensor } from './predict/catalog';
import { parseKmlToGeoJSON } from './predict/kml';
import { uploadGeometryFiles } from './predict/export';
import { computePasses, targetFromGeometry, validateTle } from './predict/passes';
import {
  DEFAULT_TARGET_BUFFER_KM,
  lookupGazetteer,
  mergePlaceHits,
  normalizeGeoHits,
  targetFromLatLon,
  targetFromPlace,
  type PlaceHit,
} from './predict/places';
import { expandPolygonKm } from './predict/geometry';
import {
  COMMON_TIMEZONES,
  calendarDayRange,
  dateFromLocalInput,
  defaultPredictWindow,
  formatUtc,
} from './predict/time';
import {
  type PredictResult,
  type PredictSatellite,
  type PredictTarget,
  type SatelliteKind,
} from './predict/types';

function parseTleBlock(text: string): { name: string | null; line1: string; line2: string } | null {
  const lines = text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);
  const l1 = lines.find((l) => l.startsWith('1 '));
  const l2 = lines.find((l) => l.startsWith('2 '));
  if (!l1 || !l2) return null;
  const nameLine = lines.find((l) => !l.startsWith('1 ') && !l.startsWith('2 '));
  return { name: nameLine || null, line1: l1, line2: l2 };
}

function newId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const DEFAULT_PREDICT_TZ = 'Asia/Karachi';

export default function PredictView({ trackedSats }: { trackedSats: TrackedSat[] }) {
  const tzDefault = DEFAULT_PREDICT_TZ;

  const [lat, setLat] = useState('');
  const [lon, setLon] = useState('');
  const [place, setPlace] = useState('');
  const [placeQuery, setPlaceQuery] = useState('');
  const [placeHits, setPlaceHits] = useState<PlaceHit[]>([]);
  const [bufferKm, setBufferKm] = useState(DEFAULT_TARGET_BUFFER_KM);
  const [polygonBuffer, setPolygonBuffer] = useState(false);
  const [target, setTarget] = useState<PredictTarget | null>(null);
  const [fileNote, setFileNote] = useState('');

  const [sats, setSats] = useState<PredictSatellite[]>([]);
  const [satName, setSatName] = useState('');
  const [line1, setLine1] = useState('');
  const [line2, setLine2] = useState('');
  const [tlePaste, setTlePaste] = useState('');
  const [searchQ, setSearchQ] = useState('');
  const [searchHits, setSearchHits] = useState<TleResult[]>([]);
  const [pendingKind, setPendingKind] = useState<'auto' | SatelliteKind>('auto');

  const [startLocal, setStartLocal] = useState('');
  const [endLocal, setEndLocal] = useState('');
  const [timeZone, setTimeZone] = useState(tzDefault);
  const [labelMin, setLabelMin] = useState<1 | 2 | 5 | 10>(5);
  const [minEl, setMinEl] = useState(10);
  const [swathKm, setSwathKm] = useState(60);
  const [allowFallback, setAllowFallback] = useState(false);

  const [computing, setComputing] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<PredictResult | null>(null);
  const [view, setView] = useState<'map' | 'report'>('map');
  const [hiddenSats, setHiddenSats] = useState<Set<string>>(new Set());
  const [hiddenPasses, setHiddenPasses] = useState<Set<string>>(new Set());
  const [showLabels, setShowLabels] = useState(true);
  const [showTarget, setShowTarget] = useState(true);
  const [showFootprints, setShowFootprints] = useState(true);
  const [cursor, setCursor] = useState('');
  const [busy, setBusy] = useState('');
  const [aoiDraw, setAoiDraw] = useState<AoiDrawMode>('off');

  const usedColors = useMemo(() => new Set(sats.map((s) => s.color)), [sats]);

  const applyTarget = (t: PredictTarget) => {
    setError('');
    setLat(t.lat.toFixed(5));
    setLon(t.lon.toFixed(5));
    setPlace(t.name);
    setTarget(t);
  };

  const applyPoint = (la: number, lo: number, name: string) => {
    if (!Number.isFinite(la) || !Number.isFinite(lo) || la < -90 || la > 90 || lo < -180 || lo > 180) {
      setError('Enter a valid latitude and longitude.');
      return;
    }
    applyTarget(targetFromLatLon(la, lo, name || 'Point', bufferKm));
  };

  const applyPlaceHit = (hit: PlaceHit) => {
    applyTarget(targetFromPlace(hit, bufferKm));
    setPlaceQuery(hit.name);
  };

  const applyDrawnAoi = (t: PredictTarget) => {
    const next =
      t.kind === 'area' && t.bufferKm == null && polygonBuffer
        ? { ...t, bufferKm, geometry: expandPolygonKm(t.geometry, bufferKm) }
        : t;
    applyTarget({ ...next, source: 'map' });
    setPlaceQuery('');
    setFileNote(next.kind === 'area' ? 'Polygon drawn on the map' : `Point drawn on the map · ${bufferKm} km AOI`);
    setAoiDraw('off');
    setResult(null);
    setView('map');
  };

  const clearTarget = () => {
    setTarget(null);
    setLat('');
    setLon('');
    setPlace('');
    setPlaceQuery('');
    setPlaceHits([]);
    setFileNote('');
    setResult(null);
    setAoiDraw('off');
  };

  const startAoiDraw = (mode: AoiDrawMode) => {
    setView('map');
    setAoiDraw((cur) => (cur === mode ? 'off' : mode));
    setError('');
  };

  const applyGeoJSON = (fc: GeoJSON.FeatureCollection, fallbackName: string) => {
    const feats = fc.features.filter((f) => f.geometry);
    if (!feats.length) throw new Error('No geometry in the file.');
    const geom =
      feats.length === 1
        ? feats[0].geometry!
        : {
            type: 'GeometryCollection' as const,
            geometries: feats.map((f) => f.geometry!),
          };
    const t0 = targetFromGeometry(geom, String(feats[0].properties?.name || fallbackName));
    if (!t0) throw new Error('Could not read coordinates from the file.');
    const t = polygonBuffer && t0.kind === 'area'
      ? { ...t0, bufferKm, geometry: expandPolygonKm(t0.geometry, bufferKm) }
      : t0;
    applyTarget(t);
    setPlaceQuery('');
    setFileNote(
      `${feats.length} feature(s) · ${t.kind}${polygonBuffer && t0.kind === 'area' ? ` · ${bufferKm} km buffer` : ''}`,
    );
  };

  const resolvePlaces = async (query: string): Promise<PlaceHit[]> => {
    const q = query.trim();
    if (!q) return [];
    const local = lookupGazetteer(q);
    try {
      const { data } = await geoApi.search(q);
      const remote = normalizeGeoHits(
        data as {
          name?: string;
          display_name?: string;
          latitude: number;
          longitude: number;
          bounding_box?: number[] | null;
        }[],
        q,
      );
      return mergePlaceHits(local, remote);
    } catch {
      return local;
    }
  };

  const searchPlace = async (query = placeQuery): Promise<PlaceHit[] | null> => {
    const q = query.trim();
    if (!q) return [];
    setBusy('place');
    try {
      const hits = await resolvePlaces(q);
      setPlaceHits(hits);
      if (hits[0]) applyPlaceHit(hits[0]);
      else setError(`No location found for "${q}". Try another spelling or lat/lng.`);
      return hits;
    } catch {
      setError('Location search failed.');
      return null;
    } finally {
      setBusy('');
    }
  };

  const onKml = async (file: File) => {
    setError('');
    setBusy('kml');
    try {
      const lower = file.name.toLowerCase();
      if (lower.endsWith('.kmz')) {
        applyGeoJSON(await uploadGeometryFiles([file]), file.name);
        return;
      }
      const text = await file.text();
      const fc = parseKmlToGeoJSON(text);
      if (fc.features.length) applyGeoJSON(fc, file.name);
      else applyGeoJSON(await uploadGeometryFiles([file]), file.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'KML parse failed.');
    } finally {
      setBusy('');
    }
  };

  const onShapefile = async (list: FileList) => {
    setError('');
    setBusy('shp');
    try {
      const fc = await uploadGeometryFiles([...list]);
      applyGeoJSON(fc, list[0]?.name || 'Shapefile');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Shapefile import failed.');
    } finally {
      setBusy('');
    }
  };

  const addSat = (name: string, l1: string, l2: string, kindOverride?: SatelliteKind) => {
    const n = name.trim() || 'Satellite';
    const invalid = validateTle(n, l1, l2);
    if (invalid) {
      setError(invalid);
      return;
    }
    const norad = noradFromLine1(l1);
    const inferred = inferSatelliteKind(n, norad);
    const kind = kindOverride ?? (pendingKind === 'auto' ? inferred : pendingKind);
    const color = colorForSatellite(n, usedColors);
    const known = knownSensor(n, norad);
    const sensor = known
      ? known
      : allowFallback
        ? { swathKm, minElevationDeg: minEl }
        : undefined;
    setSats((prev) => [
      ...prev,
      {
        id: newId(),
        name: n,
        line1: l1.trim(),
        line2: l2.trim(),
        color,
        kind,
        noradId: norad,
        sensor,
        paramsKnown: Boolean(known),
        sensorSource: known ? 'catalog' : allowFallback ? 'fallback' : 'none',
      },
    ]);
    setSatName('');
    setLine1('');
    setLine2('');
    setTlePaste('');
    if (!known && !allowFallback) {
      setError(
        `${n}: Satellite imaging parameters unavailable. Enable emergency fallback to predict with generic values.`,
      );
    } else {
      setError('');
    }
  };

  const addFromSearch = async (q: string) => {
    if (!q.trim()) return;
    setBusy('sat');
    setError('');
    try {
      const { data } = await satelliteApi.fetch(q.trim());
      setSearchHits(data.slice(0, 10));
      if (!data.length) setError(`No satellite found for "${q}".`);
    } catch {
      setError(`No satellite found for "${q}".`);
    } finally {
      setBusy('');
    }
  };

  const compute = async () => {
    setError('');
    let t = target;
    const q = placeQuery.trim();
    if (t?.source === 'upload') {
      /* keep the uploaded polygon as the primary AOI */
    } else if (q && t && t.name.trim().toLowerCase() === q.toLowerCase()) {
      t = targetFromLatLon(t.lat, t.lon, t.name, bufferKm);
      applyTarget(t);
    } else if (q) {
      const hits = await searchPlace(q);
      if (!hits || !hits.length) return;
      t = targetFromPlace(hits[0], bufferKm);
      applyTarget(t);
    } else {
      const la = Number(lat);
      const lo = Number(lon);
      if (!Number.isFinite(la) || !Number.isFinite(lo) || la < -90 || la > 90 || lo < -180 || lo > 180) {
        setError('Enter a valid latitude and longitude, or upload KML/shapefile.');
        return;
      }
      t = targetFromLatLon(la, lo, place || 'Point', bufferKm);
      setTarget(t);
    }
    if (!t) {
      setError('Set a target location or upload a polygon.');
      return;
    }
    if (!sats.length) {
      setError('Add at least one satellite TLE.');
      return;
    }
    if (!startLocal || !endLocal) {
      setError('Set a start and end time.');
      return;
    }
    const usedTarget = t;
    const startUtc = dateFromLocalInput(startLocal, timeZone);
    const endUtc = dateFromLocalInput(endLocal, timeZone);
    setComputing(true);
    window.setTimeout(() => {
      try {
        const out = computePasses(sats, usedTarget, {
          startUtc,
          endUtc,
          timeZone,
          labelIntervalMin: labelMin,
          allowFallback,
          fallbackSensor: allowFallback ? { swathKm, minElevationDeg: minEl } : undefined,
        });
        setResult(out);
        setHiddenSats(new Set());
        setHiddenPasses(new Set());
        setView('map');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Compute failed.');
      } finally {
        setComputing(false);
      }
    }, 30);
  };

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden">
      <aside className="flex h-full w-[380px] max-w-[92vw] shrink-0 flex-col border-r border-white/10 bg-gray-950">
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-cyan-400">
              A. Target location / area
            </h2>
            <label className="mb-1 block text-[11px] text-gray-400">Search place</label>
            <div className="flex gap-2">
              <input
                value={placeQuery}
                onChange={(e) => setPlaceQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void searchPlace()}
                placeholder="City or address"
                className="w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10 focus:ring-cyan-500"
              />
              <button
                onClick={() => void searchPlace()}
                className="rounded bg-white/10 px-2 text-sm hover:bg-white/20"
              >
                {busy === 'place' ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Go'}
              </button>
            </div>
            {placeHits.length > 0 && (
              <div className="mt-1 max-h-28 overflow-auto rounded bg-gray-900 text-[11px] ring-1 ring-white/10">
                {placeHits.map((h) => (
                  <button
                    key={`${h.latitude}-${h.longitude}-${h.name}`}
                    className="block w-full truncate px-2 py-1 text-left hover:bg-white/10"
                    onClick={() => applyPlaceHit(h)}
                  >
                    {h.name}
                    {h.displayName && h.displayName !== h.name ? (
                      <span className="text-gray-500"> — {h.displayName}</span>
                    ) : null}
                  </button>
                ))}
              </div>
            )}
            <div className="mt-2 grid grid-cols-2 gap-2">
              <label className="text-[11px] text-gray-400">
                Latitude
                <input
                  value={lat}
                  onChange={(e) => setLat(e.target.value)}
                  placeholder="—"
                  className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10 focus:ring-cyan-500"
                />
              </label>
              <label className="text-[11px] text-gray-400">
                Longitude
                <input
                  value={lon}
                  onChange={(e) => setLon(e.target.value)}
                  placeholder="—"
                  className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10 focus:ring-cyan-500"
                />
              </label>
            </div>
            <label className="mt-2 block text-[11px] text-gray-400">
              Location name (optional)
              <input
                value={place}
                onChange={(e) => setPlace(e.target.value)}
                className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10 focus:ring-cyan-500"
              />
            </label>
            <label className="mt-2 block text-[11px] text-gray-400">
              Target buffer (km)
              <input
                type="number"
                min={1}
                value={bufferKm}
                onChange={(e) => setBufferKm(Math.max(1, Number(e.target.value) || DEFAULT_TARGET_BUFFER_KM))}
                className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10"
              />
            </label>
            <p className="mt-1 text-[10px] text-gray-500">
              Cities and landmarks become a geodesic {bufferKm} km AOI around the geocoded point.
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <button
                onClick={() => {
                  setPlaceQuery('');
                  applyPoint(Number(lat), Number(lon), place || 'Point');
                }}
                className="inline-flex items-center gap-1 rounded bg-white/5 px-2 py-1 text-[11px] text-cyan-300 ring-1 ring-cyan-500/40 hover:bg-white/10"
              >
                <MapPin className="h-3.5 w-3.5" /> Use lat/lng
              </button>
              <button
                onClick={() => startAoiDraw('point')}
                className={`inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] ring-1 ${
                  aoiDraw === 'point'
                    ? 'bg-amber-500 text-black ring-amber-400'
                    : 'bg-white/5 text-amber-200 ring-amber-500/40 hover:bg-white/10'
                }`}
              >
                <MapPin className="h-3.5 w-3.5" /> Point on map
              </button>
              <button
                onClick={() => startAoiDraw('polygon')}
                className={`inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] ring-1 ${
                  aoiDraw === 'polygon'
                    ? 'bg-amber-500 text-black ring-amber-400'
                    : 'bg-white/5 text-amber-200 ring-amber-500/40 hover:bg-white/10'
                }`}
              >
                <Pentagon className="h-3.5 w-3.5" /> Draw polygon
              </button>
              {target ? (
                <button
                  onClick={clearTarget}
                  className="inline-flex items-center gap-1 rounded bg-white/5 px-2 py-1 text-[11px] text-gray-400 ring-1 ring-white/10 hover:bg-white/10 hover:text-red-300"
                >
                  Clear AOI
                </button>
              ) : null}
            </div>
            <p className="mt-1 text-[10px] text-gray-500">
              Place a point or polygon anywhere on the globe. Points use the {bufferKm} km target
              buffer. Drawn polygons keep their shape
              {polygonBuffer ? ` and can be buffered ${bufferKm} km` : ''}.
            </p>
            <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
              <label className="inline-flex cursor-pointer items-center gap-1 rounded bg-white/5 px-2 py-1 ring-1 ring-white/10 hover:bg-white/10">
                <Upload className="h-3.5 w-3.5" /> KML
                <input
                  type="file"
                  accept=".kml,.kmz,application/vnd.google-earth.kml+xml"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void onKml(f);
                    e.target.value = '';
                  }}
                />
              </label>
              <label className="inline-flex cursor-pointer items-center gap-1 rounded bg-white/5 px-2 py-1 ring-1 ring-white/10 hover:bg-white/10">
                <Upload className="h-3.5 w-3.5" /> Shapefile
                <input
                  type="file"
                  multiple
                  accept=".shp,.shx,.dbf,.prj,.zip,.cpg,.qpj"
                  className="hidden"
                  onChange={(e) => {
                    if (e.target.files?.length) void onShapefile(e.target.files);
                    e.target.value = '';
                  }}
                />
              </label>
              <label className="inline-flex items-center gap-1 text-gray-400">
                <input
                  type="checkbox"
                  checked={polygonBuffer}
                  onChange={() => setPolygonBuffer((v) => !v)}
                  className="accent-cyan-500"
                />
                Buffer uploaded polygon {bufferKm} km
              </label>
            </div>
            {fileNote && <p className="mt-1 text-[11px] text-emerald-400">{fileNote}</p>}
            {target && (
              <p className="mt-1 text-[11px] text-gray-500">
                Target: {target.name} ({target.kind}
                {target.bufferKm ? ` · ${target.bufferKm} km buffer` : ''}
                {target.source === 'upload'
                  ? ' · uploaded polygon'
                  : target.source === 'map'
                    ? ' · drawn on map'
                    : ''}
                ) {target.lat.toFixed(4)}, {target.lon.toFixed(4)}
              </p>
            )}
          </section>

          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-cyan-400">
              B. Satellite selection (TLE)
            </h2>
            {trackedSats.length > 0 && (
              <div className="mb-2">
                <p className="mb-1 text-[11px] text-gray-500">From live tracker</p>
                <div className="flex flex-wrap gap-1">
                  {trackedSats.map((s) => (
                    <button
                      key={s.id}
                      onClick={() => addSat(s.name, s.line1, s.line2)}
                      className="rounded-full bg-white/5 px-2 py-0.5 text-[11px] ring-1 ring-white/10 hover:bg-white/10"
                    >
                      + {s.name}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div className="flex gap-2">
              <input
                value={searchQ}
                onChange={(e) => setSearchQ(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void addFromSearch(searchQ)}
                placeholder="Celestrak name or NORAD"
                className="w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10 focus:ring-cyan-500"
              />
              <button
                onClick={() => void addFromSearch(searchQ)}
                className="rounded bg-cyan-600 px-2 text-sm hover:bg-cyan-500"
              >
                {busy === 'sat' ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Find'}
              </button>
            </div>
            {searchHits.length > 0 && (
              <div className="mt-1 max-h-28 overflow-auto rounded bg-gray-900 text-[11px] ring-1 ring-white/10">
                {searchHits.map((h) => (
                  <button
                    key={`${h.norad_id}-${h.name}`}
                    className="flex w-full justify-between px-2 py-1 text-left hover:bg-white/10"
                    onClick={() => {
                      addSat(h.name, h.line1, h.line2);
                      setSearchHits([]);
                      setSearchQ('');
                    }}
                  >
                    <span>{h.name}</span>
                    <span className="text-gray-500">{h.norad_id ?? ''}</span>
                  </button>
                ))}
              </div>
            )}
            <input
              value={satName}
              onChange={(e) => setSatName(e.target.value)}
              placeholder="Satellite name"
              className="mt-2 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10 focus:ring-cyan-500"
            />
            <textarea
              value={line1}
              onChange={(e) => setLine1(e.target.value)}
              placeholder="TLE line 1"
              rows={1}
              className="mt-1 w-full rounded bg-gray-900 px-2 py-1 font-mono text-[11px] outline-none ring-1 ring-white/10 focus:ring-cyan-500"
            />
            <textarea
              value={line2}
              onChange={(e) => setLine2(e.target.value)}
              placeholder="TLE line 2"
              rows={1}
              className="mt-1 w-full rounded bg-gray-900 px-2 py-1 font-mono text-[11px] outline-none ring-1 ring-white/10 focus:ring-cyan-500"
            />
            <textarea
              value={tlePaste}
              onChange={(e) => setTlePaste(e.target.value)}
              placeholder={'Or paste a full TLE block\nNAME\n1 ...\n2 ...'}
              rows={3}
              className="mt-1 w-full rounded bg-gray-900 px-2 py-1 font-mono text-[11px] outline-none ring-1 ring-white/10 focus:ring-cyan-500"
            />
            <div className="mt-2 flex gap-2">
              <select
                value={pendingKind}
                onChange={(e) => setPendingKind(e.target.value as 'auto' | SatelliteKind)}
                className="rounded bg-gray-900 px-2 py-1.5 text-[11px] outline-none ring-1 ring-white/10"
                title="Satellite type used for imaging rules"
              >
                <option value="auto">Type: Auto</option>
                <option value="optical">Type: Optical</option>
                <option value="sar">Type: SAR</option>
              </select>
            </div>
            <button
              onClick={() => {
                if (tlePaste.trim()) {
                  const p = parseTleBlock(tlePaste);
                  if (!p) {
                    setError('Paste a valid TLE block.');
                    return;
                  }
                  addSat(satName || p.name || 'Satellite', p.line1, p.line2);
                } else {
                  addSat(satName, line1, line2);
                }
              }}
              className="mt-2 inline-flex items-center gap-1 rounded bg-cyan-600 px-3 py-1.5 text-sm font-medium hover:bg-cyan-500"
            >
              <Plus className="h-4 w-4" /> Add satellite
            </button>
            <div className="mt-2 space-y-1">
              {sats.length === 0 && (
                <p className="text-[11px] text-gray-500">No satellites selected yet.</p>
              )}
              {sats.map((s) => {
                const known = knownSensor(s.name, s.noradId ?? null);
                const catalogNote = describeSensor(s.sensor || known || undefined);
                return (
                <div
                  key={s.id}
                  className="flex items-center gap-2 rounded bg-gray-900/70 px-2 py-1.5 text-sm ring-1 ring-white/10"
                >
                  <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: s.color }} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate">{s.name}</div>
                    {s.sensorSource === 'catalog' || known ? (
                      <div className="truncate text-[10px] text-cyan-400/90" title="Satellite-specific catalog parameters">
                        Catalog · {catalogNote}
                      </div>
                    ) : s.sensorSource === 'fallback' ? (
                      <div className="truncate text-[10px] text-amber-400">
                        Emergency fallback · {describeSensor(s.sensor)}
                      </div>
                    ) : (
                      <div className="truncate text-[10px] text-red-400">
                        Satellite imaging parameters unavailable
                      </div>
                    )}
                  </div>
                  <select
                    value={s.kind}
                    onChange={(e) =>
                      setSats((prev) =>
                        prev.map((x) =>
                          x.id === s.id ? { ...x, kind: e.target.value as SatelliteKind } : x,
                        ),
                      )
                    }
                    className="rounded bg-gray-950 px-1 py-0.5 text-[10px] text-gray-300 ring-1 ring-white/10"
                  >
                    <option value="optical">Optical</option>
                    <option value="sar">SAR</option>
                  </select>
                  <button onClick={() => setSats((p) => p.filter((x) => x.id !== s.id))}>
                    <Trash2 className="h-3.5 w-3.5 text-gray-400 hover:text-red-400" />
                  </button>
                </div>
                );
              })}
            </div>
          </section>

          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-cyan-400">
              Time window
            </h2>
            <label className="block text-[11px] text-gray-400">
              Start (12:00 AM)
              <input
                type="datetime-local"
                value={startLocal}
                onChange={(e) => setStartLocal(e.target.value)}
                className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10"
              />
            </label>
            <label className="mt-2 block text-[11px] text-gray-400">
              End (11:59 PM)
              <input
                type="datetime-local"
                value={endLocal}
                onChange={(e) => setEndLocal(e.target.value)}
                className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10"
              />
            </label>
            <div className="mt-2 flex flex-wrap gap-1">
              <button
                onClick={() => {
                  const day = calendarDayRange(timeZone);
                  setStartLocal(day.start);
                  setEndLocal(day.end);
                }}
                className="rounded bg-white/5 px-2 py-0.5 text-[11px] ring-1 ring-white/10 hover:bg-white/10"
              >
                Today 12:00 AM–11:59 PM
              </button>
              {[1, 3, 7, 14].map((d) => (
                <button
                  key={d}
                  onClick={() => {
                    const startDay = startLocal.slice(0, 10) || calendarDayRange(timeZone).start.slice(0, 10);
                    const s = dateFromLocalInput(`${startDay}T00:00`, timeZone);
                    const endAt = new Date(s.getTime() + d * 86400000);
                    const endDay = calendarDayRange(timeZone, endAt);
                    setStartLocal(`${startDay}T00:00`);
                    setEndLocal(endDay.end);
                  }}
                  className="rounded bg-white/5 px-2 py-0.5 text-[11px] ring-1 ring-white/10 hover:bg-white/10"
                >
                  +{d}d
                </button>
              ))}
            </div>
            <label className="mt-2 block text-[11px] text-gray-400">
              Time zone
              <select
                value={timeZone}
                onChange={(e) => {
                  const tz = e.target.value;
                  setTimeZone(tz);
                  const win = defaultPredictWindow(tz, 7);
                  setStartLocal(win.start);
                  setEndLocal(win.end);
                }}
                className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10"
              >
                {[timeZone, ...COMMON_TIMEZONES.filter((z) => z !== timeZone)].map((z) => (
                  <option key={z} value={z}>
                    {z}
                  </option>
                ))}
              </select>
            </label>
            <p className="mt-1 text-[11px] text-gray-500">
              Set window: 12:00 AM → 11:59 PM.
              {startLocal && endLocal ? (
                <>
                  {' '}
                  UTC: {formatUtc(dateFromLocalInput(startLocal, timeZone).toISOString(), false)} →{' '}
                  {formatUtc(dateFromLocalInput(endLocal, timeZone).toISOString(), false)}
                </>
              ) : null}
            </p>
            <label className="mt-2 block text-[11px] text-gray-400">
              Track time-label interval
              <select
                value={labelMin}
                onChange={(e) => setLabelMin(Number(e.target.value) as 1 | 2 | 5 | 10)}
                className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10"
              >
                <option value={1}>1 minute</option>
                <option value={2}>2 minutes</option>
                <option value={5}>5 minutes</option>
                <option value={10}>10 minutes</option>
              </select>
            </label>
            <label className="mt-2 flex items-start gap-2 text-[11px] text-gray-400">
              <input
                type="checkbox"
                checked={allowFallback}
                onChange={() => setAllowFallback((v) => !v)}
                className="mt-0.5 accent-amber-500"
              />
              <span>
                Emergency fallback for unknown satellites only. Known satellites always use catalog
                min elevation and swath. Do not use generic 15° / 17 km values for catalogued sensors.
              </span>
            </label>
            {allowFallback && (
              <>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <label className="text-[11px] text-amber-300/90">
                    Emergency min elevation °
                    <input
                      type="number"
                      value={minEl}
                      onChange={(e) => setMinEl(Number(e.target.value))}
                      className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-amber-500/40"
                    />
                  </label>
                  <label className="text-[11px] text-amber-300/90">
                    Emergency swath km
                    <input
                      type="number"
                      value={swathKm}
                      onChange={(e) => setSwathKm(Number(e.target.value))}
                      className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-amber-500/40"
                    />
                  </label>
                </div>
                <p className="mt-1 text-[10px] text-amber-400">
                  Fallback is an emergency mechanism. Predictions for unknown satellites will be
                  labelled as fallback, not satellite-specific.
                </p>
              </>
            )}
          </section>
        </div>
        <div className="space-y-2 border-t border-white/10 px-4 py-3">
          {error && <p className="text-xs text-red-400">{error}</p>}
          {result?.warnings.slice(0, 3).map((w) => (
            <p key={w} className="text-[11px] text-amber-400">
              {w}
            </p>
          ))}
          <button
            onClick={compute}
            disabled={computing}
            className="flex w-full items-center justify-center gap-2 rounded bg-cyan-600 py-2.5 text-sm font-semibold shadow-lg shadow-cyan-900/40 hover:bg-cyan-500 disabled:opacity-50"
          >
            {computing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Calculator className="h-4 w-4" />}
            Compute
          </button>
        </div>
      </aside>

      <div className="relative flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-white/10 bg-gray-950 px-3 py-1.5 text-[11px]">
          <button
            onClick={() => setView('map')}
            className={`rounded px-2 py-1 ${view === 'map' ? 'bg-cyan-600 text-white' : 'text-gray-400 hover:bg-white/10'}`}
          >
            Predict map
          </button>
          <button
            onClick={() => setView('report')}
            className={`rounded px-2 py-1 ${view === 'report' ? 'bg-cyan-600 text-white' : 'text-gray-400 hover:bg-white/10'}`}
          >
            Pass report ({result?.passes.length ?? 0})
          </button>
          <span className="ml-auto font-mono text-gray-500">{cursor}</span>
        </div>
        <div className="relative min-h-0 flex-1">
          {view === 'report' ? (
            <PredictReport passes={result?.passes || []} timeZone={timeZone} />
          ) : (
            <>
              <PredictMap
                target={target}
                result={result}
                hiddenSats={hiddenSats}
                hiddenPasses={hiddenPasses}
                showLabels={showLabels}
                aoiDraw={aoiDraw}
                bufferKm={bufferKm}
                aoiName={place}
                onAoiDrawn={applyDrawnAoi}
                onAoiCancel={() => setAoiDraw('off')}
                showTarget={showTarget}
                showFootprints={showFootprints}
                timeZone={timeZone}
                onCursor={setCursor}
              />
              <div className="pointer-events-auto absolute right-3 top-3 z-[1000] max-h-[calc(100%-1.5rem)] w-64 overflow-y-auto space-y-2 rounded bg-gray-950/90 p-2 text-[11px] ring-1 ring-white/10">
                <p className="font-semibold uppercase tracking-wide text-gray-300">Layers</p>
                <label className="flex items-center gap-1.5 text-gray-300">
                  <input
                    type="checkbox"
                    checked={showTarget}
                    onChange={() => setShowTarget((v) => !v)}
                    className="accent-cyan-500"
                  />
                  Target area
                </label>
                <label className="flex items-center gap-1.5 text-gray-300">
                  <input
                    type="checkbox"
                    checked={showFootprints}
                    onChange={() => setShowFootprints((v) => !v)}
                    className="accent-cyan-500"
                  />
                  Pass footprints
                </label>
                <label className="flex items-center gap-1.5 text-gray-300">
                  <input
                    type="checkbox"
                    checked={showLabels}
                    onChange={() => setShowLabels((v) => !v)}
                    className="accent-cyan-500"
                  />
                  Time labels
                </label>
                <p className="pt-1 font-semibold uppercase tracking-wide text-gray-300">Satellites</p>
                {sats.map((s) => {
                  const satPasses = (result?.passes || []).filter((p) => p.satelliteId === s.id);
                  return (
                    <div key={s.id} className="space-y-0.5">
                      <label className="flex items-center gap-1.5 text-gray-200">
                        <input
                          type="checkbox"
                          checked={!hiddenSats.has(s.id)}
                          onChange={() => {
                            setHiddenSats((prev) => {
                              const next = new Set(prev);
                              if (next.has(s.id)) next.delete(s.id);
                              else next.add(s.id);
                              return next;
                            });
                          }}
                          className="accent-cyan-500"
                        />
                        <span className="h-2 w-2 rounded-full" style={{ background: s.color }} />
                        <span className="truncate">
                          {s.name} — {s.kind === 'sar' ? 'SAR' : 'Optical'}
                        </span>
                      </label>
                      {satPasses.map((p) => (
                        <label key={p.passId} className="ml-5 flex items-start gap-1.5 text-[10px] text-gray-400">
                          <input
                            type="checkbox"
                            checked={!hiddenPasses.has(p.passId)}
                            onChange={() => {
                              setHiddenPasses((prev) => {
                                const next = new Set(prev);
                                if (next.has(p.passId)) next.delete(p.passId);
                                else next.add(p.passId);
                                return next;
                              });
                            }}
                            className="mt-0.5 accent-cyan-500"
                          />
                          <span>
                            <span className="font-mono text-gray-300">P{String(p.passNumber).padStart(3, '0')}</span>
                            {' — '}
                            {p.passDateUtc}
                            {' — '}
                            {new Intl.DateTimeFormat('en-GB', {
                              timeZone,
                              hour: '2-digit',
                              minute: '2-digit',
                              hour12: false,
                            }).format(new Date(p.startUtc))}
                            –
                            {new Intl.DateTimeFormat('en-GB', {
                              timeZone,
                              hour: '2-digit',
                              minute: '2-digit',
                              hour12: false,
                            }).format(new Date(p.endUtc))}
                          </span>
                        </label>
                      ))}
                    </div>
                  );
                })}
                {sats.length === 0 && <p className="text-gray-500">Add satellites to see tracks.</p>}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
