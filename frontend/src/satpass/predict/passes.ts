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
import type {
  ComputeOptions,
  PassRow,
  PredictResult,
  PredictSatellite,
  PredictTarget,
  SatelliteTrack,
  SensorParams,
  TrackSample,
} from './types';
import { DEFAULT_SENSOR } from './types';

const SAMPLE_MS = 15_000;
const TRACK_MS = 30_000;
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

function sunElevationDeg(date: Date, lat: number, lon: number): number {
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

function visibilityAt(date: Date, lat: number, lon: number): string {
  return sunElevationDeg(date, lat, lon) > -6 ? 'daylight' : 'night';
}

/**
 * True when the satellite can image / track the target at `date`.
 * Point targets use observer elevation (AOS/LOS).
 * Area targets use the actual polygon: SSP-inside, swath covering the geometry,
 * or (tracking) elevation at the representative point still above minEl.
 * SensorParams.swathKm / minElevationDeg are the current imaging/tracking knobs;
 * FOV and off-nadir can plug into this function later without a redesign.
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
  let globalPass = 0;

  for (const sat of satellites) {
    const invalid = validateTle(sat.name, sat.line1, sat.line2);
    if (invalid) {
      warnings.push(invalid);
      continue;
    }
    const satrec = satrecFromTle(sat.line1, sat.line2);
    const epoch = tleEpochUtc(satrec);
    if (epoch) {
      const ageDays = Math.abs(startMs - epoch.getTime()) / 86400000;
      if (ageDays > TLE_STALE_DAYS) {
        warnings.push(
          `${sat.name}: TLE epoch is ${ageDays.toFixed(1)} days from the prediction start (stale TLE; accuracy will degrade).`,
        );
      }
    }
    const sensor: SensorParams = { ...DEFAULT_SENSOR, ...sat.sensor, ...options.sensor };

    type Flag = { ms: number; covered: boolean; el: number | null };
    const flags: Flag[] = [];
    for (let t = startMs; t <= endMs; t += SAMPLE_MS) {
      const { covered, elevationDeg } = covers(satrec, new Date(t), target, sensor);
      flags.push({ ms: t, covered, el: elevationDeg });
    }

    let i = 0;
    while (i < flags.length) {
      if (!flags[i].covered) {
        i += 1;
        continue;
      }
      const a = i;
      i += 1;
      while (i < flags.length && flags[i].covered) i += 1;
      const b = i - 1;
      globalPass += 1;
      let maxEl = -Infinity;
      let maxElMs = flags[a].ms;
      for (let k = a; k <= b; k += 1) {
        if (flags[k].el != null && flags[k].el! > maxEl) {
          maxEl = flags[k].el!;
          maxElMs = flags[k].ms;
        }
      }
      const start = flags[a].ms;
      const end = flags[b].ms;
      const vis = visibilityAt(new Date(maxElMs), target.lat, target.lon);
      passes.push({
        passNumber: globalPass,
        satelliteId: sat.id,
        satelliteName: sat.name,
        color: sat.color,
        passDateUtc: iso(start).slice(0, 10),
        startUtc: iso(start),
        endUtc: iso(end),
        durationSec: Math.max(0, (end - start) / 1000),
        maxElevationDeg: Number.isFinite(maxEl) ? Math.round(maxEl * 10) / 10 : null,
        maxElevationUtc: Number.isFinite(maxEl) ? iso(maxElMs) : null,
        aosUtc: iso(start),
        losUtc: iso(end),
        visibility: vis,
      });
    }

    const satPasses = passes.filter((p) => p.satelliteId === sat.id);
    const pad = 5 * 60_000;
    const windows =
      satPasses.length === 0
        ? [{ a: startMs, b: Math.min(endMs, startMs + 95 * 60_000) }]
        : satPasses.map((p) => ({ a: Date.parse(p.startUtc) - pad, b: Date.parse(p.endUtc) + pad }));

    const samples: TrackSample[] = [];
    for (const w of windows) {
      const t0 = Math.max(startMs, w.a);
      const t1 = Math.min(endMs, w.b);
      for (let t = t0; t <= t1; t += TRACK_MS) {
        const ssp = subpoint(satrec, new Date(t));
        if (!ssp) continue;
        samples.push({ utcMs: t, lat: ssp.lat, lon: ssp.lon });
      }
    }

    const labelMs = options.labelIntervalMin * 60_000;
    const labels = [];
    for (const w of windows) {
      const t0 = Math.ceil(Math.max(startMs, w.a) / labelMs) * labelMs;
      const t1 = Math.min(endMs, w.b);
      for (let t = t0; t <= t1; t += labelMs) {
        const ssp = subpoint(satrec, new Date(t));
        if (!ssp) continue;
        const hhmm = new Intl.DateTimeFormat('en-GB', {
          timeZone: options.timeZone,
          hour: '2-digit',
          minute: '2-digit',
          hour12: false,
        }).format(new Date(t));
        labels.push({ utcMs: t, lat: ssp.lat, lon: ssp.lon, text: hhmm });
      }
    }

    tracks.push({
      satelliteId: sat.id,
      satelliteName: sat.name,
      color: sat.color,
      samples: downsample(samples, 2500),
      labels: downsample(labels, 400),
    });
  }

  if (!passes.length && !warnings.length) {
    warnings.push('No passes found in the selected window. Try a longer range or a lower minimum elevation.');
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
