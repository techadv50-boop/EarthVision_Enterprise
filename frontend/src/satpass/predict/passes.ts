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
import { centroidOfGeometry, geometryKind, minDistanceToGeometryKm } from './geometry';
import { corridorPolygon } from './footprint';
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

const SAMPLE_MS = 15_000;
const TRACK_MS = 20_000;
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
 * Geometric coverage: can the satellite see / overfly the target at `date`?
 * Imaging eligibility (optical daylight, future sensor limits) is applied later.
 */
function covers(
  satrec: SatRec,
  date: Date,
  target: PredictTarget,
  sensor: SensorParams,
): { covered: boolean; elevationDeg: number | null } {
  const ssp = subpoint(satrec, date);
  const elevationDeg = lookElevationDeg(satrec, date, target.lat, target.lon);
  if (!ssp) return { covered: false, elevationDeg };
  if (target.kind === 'point') {
    return { covered: (elevationDeg ?? -90) >= sensor.minElevationDeg, elevationDeg };
  }
  const dist = minDistanceToGeometryKm(ssp.lat, ssp.lon, target.geometry);
  const imaging = dist <= sensor.swathKm / 2;
  const tracking = (elevationDeg ?? -90) >= sensor.minElevationDeg;
  return { covered: imaging || tracking, elevationDeg };
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

type Flag = { ms: number; covered: boolean; el: number | null; sunEl: number; imaging: boolean };

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
  const samples: TrackSample[] = [];
  for (let t = startMs; t <= endMs; t += TRACK_MS) {
    const ssp = subpoint(satrec, new Date(t));
    if (!ssp) continue;
    samples.push({ utcMs: t, lat: ssp.lat, lon: ssp.lon });
  }
  if (samples.length === 1) {
    const extra = subpoint(satrec, new Date(endMs));
    if (extra) samples.push({ utcMs: endMs, lat: extra.lat, lon: extra.lon });
  }
  const labels: TrackLabel[] = [];
  const t0 = Math.ceil(startMs / labelMs) * labelMs;
  for (let t = t0; t <= endMs; t += labelMs) {
    const ssp = subpoint(satrec, new Date(t));
    if (!ssp) continue;
    const hhmm = new Intl.DateTimeFormat('en-GB', {
      timeZone,
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(new Date(t));
    labels.push({ utcMs: t, lat: ssp.lat, lon: ssp.lon, text: hhmm });
  }
  return { samples: downsample(samples, 400), labels };
}

/**
 * TLE → orbit → candidate geometric passes → satellite type rules
 * (optical daylight / SAR any local time) → unique Pass ID → footprint.
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
    const sensor = resolveSensor(sat.name, norad, options.sensor, sat.sensor);
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
    for (let t = startMs; t <= endMs; t += SAMPLE_MS) {
      const date = new Date(t);
      const { covered, elevationDeg } = covers(satrec, date, target, sensor);
      const sunEl = sunElevationDeg(date, target.lat, target.lon);
      flags.push({
        ms: t,
        covered,
        el: elevationDeg,
        sunEl,
        imaging: covered && isImagingSample(kind, imaging, sunEl),
      });
    }

    const geometric = contiguousRanges(flags, (f) => f.covered);
    let excludedNight = 0;
    let satPass = 0;

    for (const geo of geometric) {
      const imagingRanges = imaging.requiresDaylight
        ? contiguousRanges(flags.slice(geo.a, geo.b + 1), (f) => f.imaging).map((r) => ({
            a: geo.a + r.a,
            b: geo.a + r.b,
          }))
        : [geo];
      if (imaging.requiresDaylight && imagingRanges.length === 0) {
        excludedNight += 1;
        continue;
      }
      for (const win of imagingRanges) {
        if (win.b < win.a) continue;
        satPass += 1;
        let maxEl = -Infinity;
        let maxElMs = flags[win.a].ms;
        for (let k = win.a; k <= win.b; k += 1) {
          if (flags[k].el != null && flags[k].el! > maxEl) {
            maxEl = flags[k].el!;
            maxElMs = flags[k].ms;
          }
        }
        const start = flags[win.a].ms;
        const end = flags[win.b].ms;
        const vis = classifyDayNight(
          sunElevationDeg(new Date(maxElMs), target.lat, target.lon),
          target.lon,
          new Date(maxElMs),
        );
        const dateUtc = iso(start).slice(0, 10);
        const passId = makePassId(sat.name, satPass, dateUtc);
        const dash = passDashForIndex(satPass);
        const eligible = true;
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
          aosUtc: iso(flags[geo.a].ms),
          losUtc: iso(flags[geo.b].ms),
          visibility: vis,
          imagingEligible: eligible,
          imagingStatus: imagingStatusLabel(kind, vis, eligible),
        });

        const { samples, labels } = buildTrack(satrec, start, end, options.labelIntervalMin * 60_000, options.timeZone);
        tracks.push({
          passId,
          satelliteId: sat.id,
          satelliteName: sat.name,
          satelliteKind: kind,
          color: sat.color,
          dash,
          samples,
          labels,
          footprint: corridorPolygon(samples, sensor.swathKm),
        });
      }
    }

    if (excludedNight) {
      warnings.push(
        `${sat.name}: ${excludedNight} nighttime orbital pass(es) excluded (optical imaging requires daylight at the target).`,
      );
    }
  }

  if (!passes.length && !warnings.length) {
    warnings.push('No valid imaging passes in the selected window. Try a longer range, a lower minimum elevation, or (for optical) a daylight period.');
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
  };
}
