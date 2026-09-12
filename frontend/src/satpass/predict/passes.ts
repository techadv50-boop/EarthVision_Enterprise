import {
  twoline2satrec,
  propagate,
  gstime,
  eciToEcf,
  eciToGeodetic,
  degreesLat,
  degreesLong,
  degreesToRadians,
  ecfToLookAngles,
  type SatRec,
} from 'satellite.js';
import { centroidOfGeometry, geometryKind, haversineKm, minDistanceToGeometryKm } from './geometry';
import { orbitSwathPolygon } from './footprint';
import {
  classifyDayNight,
  imagingStatusLabel,
  inferSatelliteKind,
  isImagingSample,
  makePassId,
  noradFromLine1,
  passDashForIndex,
  resolveImagingRules,
  resolveSensor,
} from './catalog';
import type {
  ComputeOptions,
  PassRow,
  PredictResult,
  PredictSatellite,
  PredictTarget,
  SatelliteTrack,
  SensorParams,
  TrackLabel,
  TrackSample,
} from './types';

const SAMPLE_MS = 10_000;
const FINE_MS = 1_000;
const FINE_WHEN_KM = 250;
const TRACK_MS = 10_000;
const TLE_STALE_DAYS = 14;

function satrecFromTle(line1: string, line2: string): SatRec {
  const satrec = twoline2satrec(line1.trim(), line2.trim());
  if ((satrec as unknown as { error: number }).error) {
    throw new Error('Invalid TLE — could not parse the orbital elements.');
  }
  return satrec;
}

function tleEpochUtc(satrec: SatRec): Date | null {
  const jd = (satrec as unknown as { jdsatepoch?: number }).jdsatepoch;
  if (!jd) return null;
  return new Date((jd - 2440587.5) * 86400000);
}

function noradOf(line1: string): string {
  return line1.slice(2, 7).trim();
}

export function validateTle(name: string, line1: string, line2: string): string | null {
  const l1 = line1.trim();
  const l2 = line2.trim();
  if (!l1.startsWith('1 ') || !l2.startsWith('2 ')) {
    return `${name}: TLE lines must start with "1 " and "2 ".`;
  }
  if (l1.length < 60 || l2.length < 60) {
    return `${name}: TLE lines look too short.`;
  }
  if (noradOf(l1) !== noradOf(l2)) {
    return `${name}: TLE line 1 and line 2 NORAD ids do not match.`;
  }
  try {
    satrecFromTle(l1, l2);
  } catch (err) {
    return `${name}: ${err instanceof Error ? err.message : 'Invalid TLE.'}`;
  }
  return null;
}

function lookElevationDeg(satrec: SatRec, date: Date, lat: number, lon: number): number | null {
  const pv = propagate(satrec, date);
  if (!pv || typeof pv.position === 'boolean') return null;
  const gmst = gstime(date);
  const ecf = eciToEcf(pv.position, gmst);
  const observer = {
    longitude: degreesToRadians(lon),
    latitude: degreesToRadians(lat),
    height: 0,
  };
  const look = ecfToLookAngles(observer, ecf);
  return (look.elevation * 180) / Math.PI;
}

function subpoint(satrec: SatRec, date: Date): { lat: number; lon: number; altKm: number } | null {
  const pv = propagate(satrec, date);
  if (!pv || typeof pv.position === 'boolean') return null;
  const geo = eciToGeodetic(pv.position, gstime(date));
  return { lat: degreesLat(geo.latitude), lon: degreesLong(geo.longitude), altKm: geo.height };
}

export function sunElevationDeg(date: Date, lat: number, lon: number): number {
  const rad = Math.PI / 180;
  const day = date.getTime() / 86400000 + 2440587.5;
  const n = day - 2451545.0;
  const L = (280.46 + 0.9856474 * n) % 360;
  const g = ((357.528 + 0.9856003 * n) % 360) * rad;
  const lambda = (L + 1.915 * Math.sin(g) + 0.02 * Math.sin(2 * g)) * rad;
  const epsilon = (23.439 - 0.0000004 * n) * rad;
  const decl = Math.asin(Math.sin(epsilon) * Math.sin(lambda));
  const gmst = (18.697374558 + 24.06570982441908 * n) % 24;
  const lst = ((gmst + lon / 15) % 24) * 15 * rad;
  const ha = lst - Math.atan2(Math.cos(epsilon) * Math.sin(lambda), Math.cos(lambda));
  const elev = Math.asin(
    Math.sin(lat * rad) * Math.sin(decl) + Math.cos(lat * rad) * Math.cos(decl) * Math.cos(ha),
  );
  return elev / rad;
}

/**
 * Imaging coverage: the catalog swath must actually contain the target.
 * Horizon / min-elevation visibility alone is not an imaging pass — that was
 * counting tracks that miss Karachi (or any point) by hundreds of kilometres.
 */
export function targetInSwath(
  sspLat: number,
  sspLon: number,
  target: PredictTarget,
  swathKm: number,
): boolean {
  const dist = minDistanceToGeometryKm(sspLat, sspLon, target.geometry);
  return dist <= swathKm / 2;
}

function offNadirGroundRangeKm(altKm: number, offNadirDeg: number): number {
  if (!(altKm > 50) || !(offNadirDeg > 0)) return 0;
  const η = Math.min(offNadirDeg, 50) * (Math.PI / 180);
  return altKm * Math.tan(η);
}

/**
 * Eligibility look-reach. Catalog swath (e.g. PRSS 60 km) stays the
 * published footprint width; pointable sensors also use off-nadir ground
 * range. The drawn pass is the full pole-to-pole orbit of that revolution.
 */
function imagingReachKm(target: PredictTarget, sensor: SensorParams, altKm: number): number {
  const nadir = sensor.swathKm / 2 + (target.bufferKm || 0) + 4;
  if (sensor.maxOffNadirDeg != null && sensor.maxOffNadirDeg > 0) {
    return Math.max(nadir, offNadirGroundRangeKm(altKm > 50 ? altKm : 620, sensor.maxOffNadirDeg) + 8);
  }
  return nadir;
}

function covers(
  satrec: SatRec,
  date: Date,
  target: PredictTarget,
  sensor: SensorParams,
): { covered: boolean; elevationDeg: number | null; distKm: number } {
  const ssp = subpoint(satrec, date);
  const elevationDeg = lookElevationDeg(satrec, date, target.lat, target.lon);
  if (!ssp) return { covered: false, elevationDeg, distKm: Infinity };
  const distKm = minDistanceToGeometryKm(ssp.lat, ssp.lon, target.geometry);
  const inReach = distKm <= imagingReachKm(target, sensor, ssp.altKm);
  const highEnough = (elevationDeg ?? -90) >= sensor.minElevationDeg;
  return { covered: inReach && highEnough, elevationDeg, distKm };
}

function iso(ms: number): string {
  return new Date(ms).toISOString();
}

function downsample<T>(items: T[], max: number): T[] {
  if (items.length <= max) return items;
  const step = items.length / max;
  const out: T[] = [];
  for (let i = 0; i < max; i += 1) out.push(items[Math.floor(i * step)]);
  if (out[out.length - 1] !== items[items.length - 1]) out.push(items[items.length - 1]);
  return out;
}

type Flag = {
  ms: number;
  visible: boolean;
  covered: boolean;
  el: number | null;
  sunEl: number;
  imaging: boolean;
};

function contiguousRanges(flags: Flag[], pred: (f: Flag) => boolean): { a: number; b: number }[] {
  const ranges: { a: number; b: number }[] = [];
  let i = 0;
  while (i < flags.length) {
    if (!pred(flags[i])) {
      i += 1;
      continue;
    }
    const a = i;
    i += 1;
    while (i < flags.length && pred(flags[i])) i += 1;
    ranges.push({ a, b: i - 1 });
  }
  return ranges;
}

function buildTrack(
  satrec: SatRec,
  startMs: number,
  endMs: number,
  labelMs: number,
  timeZone: string,
): { samples: TrackSample[]; labels: TrackLabel[] } {
  const span = Math.max(0, endMs - startMs);
  const step = span <= 180_000 ? 1_000 : TRACK_MS;
  const samples: TrackSample[] = [];
  for (let t = startMs; t <= endMs; t += step) {
    const ssp = subpoint(satrec, new Date(t));
    if (!ssp) continue;
    samples.push({ utcMs: t, lat: ssp.lat, lon: ssp.lon });
  }
  const endSsp = subpoint(satrec, new Date(endMs));
  if (endSsp && (!samples.length || samples[samples.length - 1].utcMs !== endMs)) {
    samples.push({ utcMs: endMs, lat: endSsp.lat, lon: endSsp.lon });
  }
  if (samples.length === 1 && endSsp) {
    const extra = subpoint(satrec, new Date(endMs + 1000));
    if (extra) samples.push({ utcMs: endMs + 1000, lat: extra.lat, lon: extra.lon });
  }
  const labels: TrackLabel[] = [];
  const labelStep = span <= 180_000 ? Math.max(2_000, Math.floor(span / 4) || 2_000) : labelMs;
  const t0 = Math.ceil(startMs / labelStep) * labelStep;
  for (let t = t0; t <= endMs; t += labelStep) {
    const ssp = subpoint(satrec, new Date(t));
    if (!ssp) continue;
    const hhmm = new Intl.DateTimeFormat('en-GB', {
      timeZone,
      hour: '2-digit',
      minute: '2-digit',
      ...(span <= 180_000 ? { second: '2-digit' as const } : {}),
      hour12: false,
    }).format(new Date(t));
    labels.push({ utcMs: t, lat: ssp.lat, lon: ssp.lon, text: hhmm });
  }
  if (!labels.length && samples.length) {
    const s = samples[Math.floor(samples.length / 2)];
    labels.push({
      utcMs: s.utcMs,
      lat: s.lat,
      lon: s.lon,
      text: new Intl.DateTimeFormat('en-GB', {
        timeZone,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      }).format(new Date(s.utcMs)),
    });
  }
  return { samples: downsample(samples, 400), labels };
}

const POLE_STEP_MS = 20_000;
const POLE_HALF_MS = 70 * 60_000;

function sspLat(satrec: SatRec, ms: number): number | null {
  const ssp = subpoint(satrec, new Date(ms));
  return ssp ? ssp.lat : null;
}

/** Walk toward a latitude turning point (near-polar extreme of this revolution). */
function latExtremumMs(satrec: SatRec, fromMs: number, dir: -1 | 1): number {
  let t = fromMs;
  let prev = sspLat(satrec, t);
  if (prev == null) return fromMs;
  let prevD = 0;
  let haveD = false;
  const limit = fromMs + dir * POLE_HALF_MS;
  for (let i = 0; i < 240; i += 1) {
    t += dir * POLE_STEP_MS;
    if ((dir > 0 && t > limit) || (dir < 0 && t < limit)) break;
    const lat = sspLat(satrec, t);
    if (lat == null) continue;
    const d = lat - prev;
    if (haveD && prevD !== 0 && d !== 0 && Math.sign(d) !== Math.sign(prevD)) {
      return t - dir * (POLE_STEP_MS / 2);
    }
    if (d !== 0) {
      prevD = d;
      haveD = true;
    }
    prev = lat;
  }
  return t;
}

/** North-extreme → south-extreme (or vice versa) of the revolution that images the target. */
function poleToPoleWindow(satrec: SatRec, midMs: number): { startMs: number; endMs: number } {
  const startMs = latExtremumMs(satrec, midMs, -1);
  const endMs = latExtremumMs(satrec, midMs, 1);
  if (endMs > startMs + 60_000) return { startMs, endMs };
  return { startMs: midMs - 25 * 60_000, endMs: midMs + 25 * 60_000 };
}

const LABEL_MIN_SEP_KM = 650;

function spaceLabels(labels: TrackLabel[]): TrackLabel[] {
  const out: TrackLabel[] = [];
  for (const lab of labels) {
    if (out.some((k) => haversineKm(k.lat, k.lon, lab.lat, lab.lon) < LABEL_MIN_SEP_KM)) continue;
    out.push(lab);
  }
  return out;
}

/**
 * Pipeline (kept distinct on purpose):
 *   A. Orbital pass        — TLE propagation
 *   B. Visibility pass     — elevation above horizon (internal only)
 *   C. Imaging-eligible    — min elevation + catalog swath / off-nadir look
 *   D. Target-AOI intersect — SSP within imaging reach of the AOI
 *   E. Displayed pass      — pole-to-pole ground track of that revolution
 *   F. Imaging footprint   — catalog-swath parallelogram along that track
 *
 * Only imaging-eligible revolutions are published; each is drawn in full.
 */
export function computePasses(
  satellites: PredictSatellite[],
  target: PredictTarget,
  options: ComputeOptions,
): PredictResult {
  const warnings: string[] = [];
  const startMs = options.startUtc.getTime();
  const endMs = options.endUtc.getTime();
  if (!(endMs > startMs)) {
    return { warnings: ['End time must be after start time.'], passes: [], tracks: [] };
  }
  if (endMs - startMs > 14 * 86400000) {
    warnings.push('Prediction window is longer than 14 days; results may be slow and TLE accuracy drops.');
  }

  const passes: PassRow[] = [];
  const tracks: SatelliteTrack[] = [];

  for (const sat of satellites) {
    const invalid = validateTle(sat.name, sat.line1, sat.line2);
    if (invalid) {
      warnings.push(invalid);
      continue;
    }
    const satrec = satrecFromTle(sat.line1, sat.line2);
    const norad = sat.noradId ?? noradFromLine1(sat.line1);
    const kind = sat.kind || inferSatelliteKind(sat.name, norad);
    const imaging = resolveImagingRules(kind, sat.imaging);
    const resolved = resolveSensor(
      sat.name,
      norad,
      sat.sensor,
      options.allowFallback ? options.fallbackSensor : undefined,
    );
    if (!resolved) {
      warnings.push(
        `${sat.name}: Satellite imaging parameters unavailable. Prediction is based only on orbital geometry — no imaging pass is reported.`,
      );
      continue;
    }
    const sensor = resolved.sensor;
    if (resolved.source === 'fallback') {
      warnings.push(
        `${sat.name}: using emergency fallback swath/elevation (not satellite-specific catalog values).`,
      );
    }
    const epoch = tleEpochUtc(satrec);
    if (epoch) {
      const ageDays = Math.abs(startMs - epoch.getTime()) / 86400000;
      if (ageDays > TLE_STALE_DAYS) {
        warnings.push(
          `${sat.name}: TLE epoch is ${ageDays.toFixed(1)} days from the prediction start (stale TLE; accuracy will degrade).`,
        );
      }
    }

    const flags: Flag[] = [];
    for (let t = startMs; t <= endMs; ) {
      const date = new Date(t);
      const { covered, elevationDeg, distKm } = covers(satrec, date, target, sensor);
      const sunEl = sunElevationDeg(date, target.lat, target.lon);
      const visible = (elevationDeg ?? -90) >= 0;
      flags.push({
        ms: t,
        visible,
        covered,
        el: elevationDeg,
        sunEl,
        imaging: covered && isImagingSample(kind, imaging, sunEl),
      });
      t += distKm < FINE_WHEN_KM ? FINE_MS : SAMPLE_MS;
    }

    // Report only imaging-eligible AOI intersections; draw each as a pole-to-pole pass.
    const imagingWindows = contiguousRanges(flags, (f) => f.imaging);
    let satPass = 0;
    let skippedNight = 0;
    let skippedGeometry = 0;
    const visWindows = contiguousRanges(flags, (f) => f.visible);
    for (const vis of visWindows) {
      const slice = flags.slice(vis.a, vis.b + 1);
      if (slice.some((f) => f.covered) && !slice.some((f) => f.imaging)) skippedNight += 1;
      else if (slice.some((f) => f.visible) && !slice.some((f) => f.covered)) skippedGeometry += 1;
    }

    for (const win of imagingWindows) {
      if (win.b < win.a) continue;
      const rawStart = flags[win.a].ms;
      const rawEnd = flags[win.b].ms;
      const midMs = rawStart + Math.max(0, (rawEnd - rawStart) / 2);
      const orbit = poleToPoleWindow(satrec, midMs);
      const built = buildTrack(
        satrec,
        orbit.startMs,
        orbit.endMs,
        options.labelIntervalMin * 60_000,
        options.timeZone,
      );
      const samples = built.samples;
      if (samples.length < 2) continue;
      const labelsKept = spaceLabels(built.labels);

      satPass += 1;
      const start = rawStart;
      const end = rawEnd;
      let maxEl = -Infinity;
      let maxElMs = midMs;
      for (let k = win.a; k <= win.b; k += 1) {
        if (flags[k].el != null && flags[k].el! > maxEl) {
          maxEl = flags[k].el!;
          maxElMs = flags[k].ms;
        }
      }
      const vis = classifyDayNight(
        sunElevationDeg(new Date(maxElMs), target.lat, target.lon),
        target.lon,
        new Date(maxElMs),
      );
      const dateUtc = iso(maxElMs).slice(0, 10);
      const passId = makePassId(sat.name, satPass, dateUtc);
      const dash = passDashForIndex(satPass);
      passes.push({
        passId,
        passNumber: satPass,
        satelliteId: sat.id,
        satelliteName: sat.name,
        satelliteKind: kind,
        noradId: norad,
        color: sat.color,
        dash,
        passDateUtc: dateUtc,
        startUtc: iso(start),
        endUtc: iso(end),
        durationSec: Math.max(0, (end - start) / 1000),
        maxElevationDeg: Number.isFinite(maxEl) ? Math.round(maxEl * 10) / 10 : null,
        maxElevationUtc: Number.isFinite(maxEl) ? iso(maxElMs) : null,
        aosUtc: iso(start),
        losUtc: iso(end),
        visibility: vis,
        imagingEligible: true,
        imagingStatus: imagingStatusLabel(kind, vis, true),
        targetName: target.name,
        minElevationDeg: sensor.minElevationDeg,
        swathKm: sensor.swathKm,
        sensorSource: resolved.source,
      });

      tracks.push({
        passId,
        satelliteId: sat.id,
        satelliteName: sat.name,
        satelliteKind: kind,
        color: sat.color,
        dash,
        samples,
        labels: labelsKept,
        footprint: orbitSwathPolygon(samples, sensor.swathKm),
      });
    }

    if (skippedNight) {
      warnings.push(
        `${sat.name}: ${skippedNight} nighttime orbital pass(es) excluded (optical imaging requires daylight at the target).`,
      );
    }
    if (skippedGeometry && !satPass) {
      const look =
        sensor.maxOffNadirDeg != null
          ? `${sensor.swathKm} km swath / ${sensor.maxOffNadirDeg}° off-nadir look`
          : `${sensor.swathKm} km swath`;
      warnings.push(
        `${sat.name}: ${skippedGeometry} horizon pass(es) did not cover the target AOI with the ${look} and ${sensor.minElevationDeg}° min elevation.`,
      );
    }
  }

  if (!passes.length) {
    warnings.push(
      'No imaging-eligible passes cover the target AOI in this window. A pass is reported only when the catalog swath, off-nadir look (when published), and minimum elevation cover the AOI (optical: daylight only). Try a longer range.',
    );
  }

  return { warnings, passes, tracks };
}

export function featureCollectionFromTarget(target: PredictTarget): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { name: target.name },
        geometry: target.geometry,
      },
    ],
  };
}

export function targetFromGeometry(geometry: GeoJSON.Geometry, name: string): PredictTarget | null {
  const c = centroidOfGeometry(geometry);
  if (!c) return null;
  return {
    kind: geometryKind(geometry),
    name: name || 'Target',
    geometry,
    lon: c.lon,
    lat: c.lat,
    source: 'upload',
  };
}
