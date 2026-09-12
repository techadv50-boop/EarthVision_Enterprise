// SGP4 orbit math for SatPass. All the "hard" TLE work lives here so the UI
// only deals with lat / lon / altitude. Powered by satellite.js.
import {
  twoline2satrec,
  propagate,
  gstime,
  eciToGeodetic,
  degreesLong,
  degreesLat,
  type SatRec,
} from 'satellite.js';
import { canonicalizeTle } from './tle';

const EARTH_RADIUS_KM = 6371;

export interface SatState {
  lon: number; // degrees
  lat: number; // degrees
  altKm: number; // km above the surface
  speedKmS: number; // km/s
}

export function parseTle(line1: string, line2: string): SatRec {
  const tle = canonicalizeTle(line1, line2);
  const satrec = twoline2satrec(tle.line1, tle.line2);
  // satellite.js sets a non-zero error code on invalid element sets.
  if ((satrec as unknown as { error: number }).error) {
    throw new Error('Invalid TLE — could not parse the orbital elements.');
  }
  return satrec;
}

function isVec(v: unknown): v is { x: number; y: number; z: number } {
  if (!v || typeof v !== 'object') return false;
  const o = v as { x?: unknown; y?: unknown; z?: unknown };
  return Number.isFinite(o.x) && Number.isFinite(o.y) && Number.isFinite(o.z);
}

/** Propagate the satellite to `date` and return its geodetic state, or null on failure. */
export function getState(satrec: SatRec, date: Date): SatState | null {
  try {
    const pv = propagate(satrec, date);
    if (!pv || !isVec(pv.position) || !isVec(pv.velocity)) return null;
    const gmst = gstime(date);
    const geo = eciToGeodetic(pv.position, gmst);
    const { velocity } = pv;
    const speedKmS = Math.sqrt(
      velocity.x * velocity.x + velocity.y * velocity.y + velocity.z * velocity.z,
    );
    if (!Number.isFinite(geo.latitude) || !Number.isFinite(geo.longitude)) return null;
    return {
      lon: degreesLong(geo.longitude),
      lat: degreesLat(geo.latitude),
      altKm: geo.height,
      speedKmS,
    };
  } catch {
    return null;
  }
}

/** Orbital period in minutes derived from the TLE mean motion. */
export function periodMinutes(satrec: SatRec): number {
  const noRadPerMin = (satrec as unknown as { no: number }).no; // radians / minute
  if (!noRadPerMin || noRadPerMin <= 0) return 90;
  return (2 * Math.PI) / noRadPerMin;
}

/**
 * Radius (in metres) of the ground footprint the satellite can currently "see":
 * the circle on Earth where the satellite is above the local horizon.
 */
export function footprintRadiusMeters(altKm: number): number {
  const ratio = EARTH_RADIUS_KM / (EARTH_RADIUS_KM + Math.max(altKm, 1));
  const centralAngle = Math.acos(Math.min(1, Math.max(-1, ratio)));
  return EARTH_RADIUS_KM * centralAngle * 1000;
}

export interface TrackPoint {
  lon: number;
  lat: number;
}

/**
 * Sample the sub-satellite ground track for roughly one orbit centred on `date`.
 * Returns segments split at the antimeridian so polylines don't smear across the map.
 */
export function groundTrack(satrec: SatRec, date: Date, points = 180): TrackPoint[][] {
  const period = periodMinutes(satrec);
  const startMs = date.getTime() - (period / 2) * 60_000;
  const stepMs = (period * 60_000) / points;

  const segments: TrackPoint[][] = [];
  let current: TrackPoint[] = [];
  let prevLon: number | null = null;

  for (let i = 0; i <= points; i += 1) {
    const state = getState(satrec, new Date(startMs + i * stepMs));
    if (!state) continue;
    if (prevLon !== null && Math.abs(state.lon - prevLon) > 180) {
      if (current.length) segments.push(current);
      current = [];
    }
    current.push({ lon: state.lon, lat: state.lat });
    prevLon = state.lon;
  }
  if (current.length) segments.push(current);
  return segments;
}
