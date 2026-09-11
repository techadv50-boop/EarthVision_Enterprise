import { useMemo, useState } from 'react';
import {
  Plus,
  Trash2,
  Loader2,
  Upload,
  MapPin,
  Calculator,
} from 'lucide-react';
import { geoApi, satelliteApi, type TleResult } from '@/services/api';
import type { TrackedSat } from './SatPassMap';
import PredictMap from './PredictMap';
import PredictReport from './PredictReport';
import { colorForSatellite } from './predict/colors';
import { parseKmlToGeoJSON } from './predict/kml';
import { uploadGeometryFiles } from './predict/export';
import { computePasses, targetFromGeometry, validateTle } from './predict/passes';
import {
  COMMON_TIMEZONES,
  dateFromLocalInput,
  formatUtc,
  localInputFromDate,
} from './predict/time';
import { DEFAULT_SENSOR, type PredictResult, type PredictSatellite, type PredictTarget } from './predict/types';

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

function defaultRange(timeZone: string) {
  const start = new Date();
  start.setUTCMinutes(0, 0, 0);
  const end = new Date(start.getTime() + 3 * 86400000);
  return { start: localInputFromDate(start, timeZone), end: localInputFromDate(end, timeZone) };
}

export default function PredictView({ trackedSats }: { trackedSats: TrackedSat[] }) {
  const tzDefault = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const range0 = useMemo(() => defaultRange(tzDefault), [tzDefault]);

  const [lat, setLat] = useState('33.6844');
  const [lon, setLon] = useState('73.0479');
  const [place, setPlace] = useState('Islamabad');
  const [placeQuery, setPlaceQuery] = useState('');
  const [placeHits, setPlaceHits] = useState<{ name: string; latitude: number; longitude: number }[]>([]);
  const [target, setTarget] = useState<PredictTarget | null>({
    kind: 'point',
    name: 'Islamabad',
    lat: 33.6844,
    lon: 73.0479,
    geometry: { type: 'Point', coordinates: [73.0479, 33.6844] },
  });
  const [fileNote, setFileNote] = useState('');

  const [sats, setSats] = useState<PredictSatellite[]>([]);
  const [satName, setSatName] = useState('');
  const [line1, setLine1] = useState('');
  const [line2, setLine2] = useState('');
  const [tlePaste, setTlePaste] = useState('');
  const [searchQ, setSearchQ] = useState('');
  const [searchHits, setSearchHits] = useState<TleResult[]>([]);

  const [startLocal, setStartLocal] = useState(range0.start);
  const [endLocal, setEndLocal] = useState(range0.end);
  const [timeZone, setTimeZone] = useState(tzDefault);
  const [labelMin, setLabelMin] = useState<1 | 2 | 5 | 10>(2);
  const [minEl, setMinEl] = useState(10);
  const [swathKm, setSwathKm] = useState(60);

  const [computing, setComputing] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<PredictResult | null>(null);
  const [view, setView] = useState<'map' | 'report'>('map');
  const [hiddenSats, setHiddenSats] = useState<Set<string>>(new Set());
  const [showLabels, setShowLabels] = useState(true);
  const [showTarget, setShowTarget] = useState(true);
  const [cursor, setCursor] = useState('');
  const [busy, setBusy] = useState('');

  const usedColors = useMemo(() => new Set(sats.map((s) => s.color)), [sats]);

  const applyPoint = (la: number, lo: number, name: string) => {
    if (!Number.isFinite(la) || !Number.isFinite(lo) || la < -90 || la > 90 || lo < -180 || lo > 180) {
      setError('Enter a valid latitude and longitude.');
      return;
    }
    setError('');
    setLat(String(la));
    setLon(String(lo));
    setPlace(name);
    setTarget({
      kind: 'point',
      name: name || 'Point',
      lon: lo,
      lat: la,
      geometry: { type: 'Point', coordinates: [lo, la] },
    });
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
    const t = targetFromGeometry(geom, String(feats[0].properties?.name || fallbackName));
    if (!t) throw new Error('Could not read coordinates from the file.');
    setTarget(t);
    setLat(t.lat.toFixed(5));
    setLon(t.lon.toFixed(5));
    setPlace(t.name);
    setFileNote(`${feats.length} feature(s) · ${t.kind}`);
  };

  const searchPlace = async () => {
    if (!placeQuery.trim()) return;
    setBusy('place');
    try {
      const { data } = await geoApi.search(placeQuery.trim());
      const hits = (data as { name?: string; display_name?: string; latitude: number; longitude: number }[]).map(
        (h) => ({
          name: h.name || h.display_name || placeQuery,
          latitude: h.latitude,
          longitude: h.longitude,
        }),
      );
      setPlaceHits(hits);
      if (hits[0]) applyPoint(hits[0].latitude, hits[0].longitude, hits[0].name);
    } catch {
      setError('Location search failed.');
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

  const addSat = (name: string, l1: string, l2: string) => {
    const n = name.trim() || 'Satellite';
    const invalid = validateTle(n, l1, l2);
    if (invalid) {
      setError(invalid);
      return;
    }
    const color = colorForSatellite(n, usedColors);
    setSats((prev) => [...prev, { id: newId(), name: n, line1: l1.trim(), line2: l2.trim(), color }]);
    setSatName('');
    setLine1('');
    setLine2('');
    setTlePaste('');
    setError('');
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

  const compute = () => {
    setError('');
    let t = target;
    if (!t || t.kind === 'point') {
      const la = Number(lat);
      const lo = Number(lon);
      if (!Number.isFinite(la) || !Number.isFinite(lo) || la < -90 || la > 90 || lo < -180 || lo > 180) {
        setError('Enter a valid latitude and longitude, or upload KML/shapefile.');
        return;
      }
      t = {
        kind: 'point',
        name: place || 'Point',
        lat: la,
        lon: lo,
        geometry: { type: 'Point', coordinates: [lo, la] },
      };
      setTarget(t);
    }
    if (!sats.length) {
      setError('Add at least one satellite TLE.');
      return;
    }
    const startUtc = dateFromLocalInput(startLocal, timeZone);
    const endUtc = dateFromLocalInput(endLocal, timeZone);
    setComputing(true);
    window.setTimeout(() => {
      try {
        const out = computePasses(sats, t, {
          startUtc,
          endUtc,
          timeZone,
          labelIntervalMin: labelMin,
          sensor: { ...DEFAULT_SENSOR, minElevationDeg: minEl, swathKm },
        });
        setResult(out);
        setHiddenSats(new Set());
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
            {placeHits.length > 1 && (
              <div className="mt-1 max-h-24 overflow-auto rounded bg-gray-900 text-[11px] ring-1 ring-white/10">
                {placeHits.map((h) => (
                  <button
                    key={`${h.latitude}-${h.longitude}`}
                    className="block w-full truncate px-2 py-1 text-left hover:bg-white/10"
                    onClick={() => applyPoint(h.latitude, h.longitude, h.name)}
                  >
                    {h.name}
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
                  className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10 focus:ring-cyan-500"
                />
              </label>
              <label className="text-[11px] text-gray-400">
                Longitude
                <input
                  value={lon}
                  onChange={(e) => setLon(e.target.value)}
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
            <button
              onClick={() => applyPoint(Number(lat), Number(lon), place || 'Point')}
              className="mt-2 inline-flex items-center gap-1 rounded bg-white/5 px-2 py-1 text-[11px] text-cyan-300 ring-1 ring-cyan-500/40 hover:bg-white/10"
            >
              <MapPin className="h-3.5 w-3.5" /> Use lat/lng
            </button>
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
            </div>
            {fileNote && <p className="mt-1 text-[11px] text-emerald-400">{fileNote}</p>}
            {target && (
              <p className="mt-1 text-[11px] text-gray-500">
                Target: {target.name} ({target.kind}) {target.lat.toFixed(3)}, {target.lon.toFixed(3)}
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
              {sats.map((s) => (
                <div
                  key={s.id}
                  className="flex items-center gap-2 rounded bg-gray-900/70 px-2 py-1.5 text-sm ring-1 ring-white/10"
                >
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: s.color }} />
                  <span className="flex-1 truncate">{s.name}</span>
                  <button onClick={() => setSats((p) => p.filter((x) => x.id !== s.id))}>
                    <Trash2 className="h-3.5 w-3.5 text-gray-400 hover:text-red-400" />
                  </button>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-cyan-400">
              Time window
            </h2>
            <label className="block text-[11px] text-gray-400">
              Start
              <input
                type="datetime-local"
                value={startLocal}
                onChange={(e) => setStartLocal(e.target.value)}
                className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10"
              />
            </label>
            <label className="mt-2 block text-[11px] text-gray-400">
              End
              <input
                type="datetime-local"
                value={endLocal}
                onChange={(e) => setEndLocal(e.target.value)}
                className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10"
              />
            </label>
            <div className="mt-2 flex gap-1">
              {[1, 3, 7].map((d) => (
                <button
                  key={d}
                  onClick={() => {
                    const s = dateFromLocalInput(startLocal, timeZone);
                    setEndLocal(localInputFromDate(new Date(s.getTime() + d * 86400000), timeZone));
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
                onChange={(e) => setTimeZone(e.target.value)}
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
              UTC window: {formatUtc(dateFromLocalInput(startLocal, timeZone).toISOString(), false)} →{' '}
              {formatUtc(dateFromLocalInput(endLocal, timeZone).toISOString(), false)}
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
            <div className="mt-2 grid grid-cols-2 gap-2">
              <label className="text-[11px] text-gray-400">
                Min elevation °
                <input
                  type="number"
                  value={minEl}
                  onChange={(e) => setMinEl(Number(e.target.value))}
                  className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10"
                />
              </label>
              <label className="text-[11px] text-gray-400">
                Swath km
                <input
                  type="number"
                  value={swathKm}
                  onChange={(e) => setSwathKm(Number(e.target.value))}
                  className="mt-0.5 w-full rounded bg-gray-900 px-2 py-1.5 text-sm outline-none ring-1 ring-white/10"
                />
              </label>
            </div>
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
            Ground-track map
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
                showLabels={showLabels}
                showTarget={showTarget}
                onCursor={setCursor}
              />
              <div className="pointer-events-auto absolute right-3 top-3 z-[1000] w-52 space-y-2 rounded bg-gray-950/90 p-2 text-[11px] ring-1 ring-white/10">
                <p className="font-semibold text-gray-300">Layers</p>
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
                    checked={showLabels}
                    onChange={() => setShowLabels((v) => !v)}
                    className="accent-cyan-500"
                  />
                  Time labels
                </label>
                <p className="pt-1 font-semibold text-gray-300">Legend</p>
                {sats.map((s) => (
                  <label key={s.id} className="flex items-center gap-1.5 text-gray-300">
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
                    <span className="truncate">{s.name}</span>
                  </label>
                ))}
                {sats.length === 0 && <p className="text-gray-500">Add satellites to see tracks.</p>}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
