/** Build a closed imaging-corridor polygon around a ground-track segment. */

import { geodesicCirclePolygon, minDistanceToGeometryKm } from './geometry';
import type { PredictTarget } from './types';

const R_KM = 6371;

export function destinationPoint(
  lat: number,
  lon: number,
  bearingDeg: number,
  distKm: number,
): { lat: number; lon: number } {
  const δ = distKm / R_KM;
  const θ = (bearingDeg * Math.PI) / 180;
  const φ1 = (lat * Math.PI) / 180;
  const λ1 = (lon * Math.PI) / 180;
  const sinφ2 = Math.sin(φ1) * Math.cos(δ) + Math.cos(φ1) * Math.sin(δ) * Math.cos(θ);
  const φ2 = Math.asin(Math.min(1, Math.max(-1, sinφ2)));
  const λ2 =
    λ1 +
    Math.atan2(Math.sin(θ) * Math.sin(δ) * Math.cos(φ1), Math.cos(δ) - Math.sin(φ1) * Math.sin(φ2));
  return { lat: (φ2 * 180) / Math.PI, lon: ((((λ2 * 180) / Math.PI + 540) % 360) - 180) };
}

export function bearingDeg(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const φ1 = (lat1 * Math.PI) / 180;
  const φ2 = (lat2 * Math.PI) / 180;
  const Δλ = ((lon2 - lon1) * Math.PI) / 180;
  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

function unwrap(samples: { lat: number; lon: number }[]): { lat: number; lon: number }[] {
  if (!samples.length) return [];
  const out = [{ lat: samples[0].lat, lon: samples[0].lon }];
  for (let i = 1; i < samples.length; i += 1) {
    let lon = samples[i].lon;
    const prev = out[i - 1].lon;
    while (lon - prev > 180) lon -= 360;
    while (lon - prev < -180) lon += 360;
    out.push({ lat: samples[i].lat, lon });
  }
  return out;
}

function wrapLon(lon: number): number {
  return ((((lon + 180) % 360) + 360) % 360) - 180;
}

/**
 * Corridor polygon: left/right offsets of swathKm/2 along the track heading.
 * One polygon per pass — never a combined rectangle for all passes.
 */
export function corridorPolygon(
  samples: { lat: number; lon: number }[],
  swathKm: number,
): GeoJSON.Polygon | null {
  if (samples.length < 2 || !(swathKm > 0)) return null;
  const pts = unwrap(samples);
  const half = swathKm / 2;
  const left: [number, number][] = [];
  const right: [number, number][] = [];
  for (let i = 0; i < pts.length; i += 1) {
    const prev = pts[Math.max(0, i - 1)];
    const next = pts[Math.min(pts.length - 1, i + 1)];
    const hdg = bearingDeg(prev.lat, prev.lon, next.lat, next.lon);
    const l = destinationPoint(pts[i].lat, pts[i].lon, hdg - 90, half);
    const r = destinationPoint(pts[i].lat, pts[i].lon, hdg + 90, half);
    left.push([wrapLon(l.lon), l.lat]);
    right.push([wrapLon(r.lon), r.lat]);
  }
  const ring = [...left, ...right.reverse()];
  const first = ring[0];
  ring.push([first[0], first[1]]);
  if (ring.length < 4) return null;
  return { type: 'Polygon', coordinates: [ring] };
}

/**
 * Keep only the portion of a corridor that lies within swath reach of the
 * Target AOI so footprints cannot stretch across unrelated countries.
 */
export function clipPolygonToAoiCoverage(
  poly: GeoJSON.Polygon,
  target: PredictTarget,
  swathKm: number,
): GeoJSON.Polygon | null {
  const maxDist = swathKm / 2 + 1;
  const ring = poly.coordinates[0] || [];
  if (ring.length < 4) return null;
  const kept: [number, number][] = [];
  const inside = (lon: number, lat: number) => minDistanceToGeometryKm(lat, lon, target.geometry) <= maxDist;
  for (let i = 0; i < ring.length - 1; i += 1) {
    const a = ring[i];
    const b = ring[i + 1];
    const ain = inside(a[0], a[1]);
    const bin = inside(b[0], b[1]);
    if (ain) kept.push([a[0], a[1]]);
    if (ain !== bin) {
      let lo = 0;
      let hi = 1;
      for (let k = 0; k < 14; k += 1) {
        const m = (lo + hi) / 2;
        const lon = a[0] + (b[0] - a[0]) * m;
        const lat = a[1] + (b[1] - a[1]) * m;
        if (inside(lon, lat) === ain) lo = m;
        else hi = m;
      }
      const m = (lo + hi) / 2;
      kept.push([a[0] + (b[0] - a[0]) * m, a[1] + (b[1] - a[1]) * m]);
    }
  }
  if (kept.length < 3) {
    return geodesicCirclePolygon(target.lat, target.lon, (target.bufferKm || 0) + swathKm / 2);
  }
  const closed = [...kept, kept[0]];
  return { type: 'Polygon', coordinates: [closed] };
}

/** Sensor corridor along the clipped pass, then clipped to AOI coverage. */
export function imagingFootprint(
  samples: { lat: number; lon: number }[],
  swathKm: number,
  target: PredictTarget,
): GeoJSON.Polygon | null {
  const reach = swathKm / 2 + 2;
  const near = samples.filter((s) => minDistanceToGeometryKm(s.lat, s.lon, target.geometry) <= reach);
  const poly = corridorPolygon(near.length >= 2 ? near : samples, swathKm);
  if (!poly) {
    if (near.length === 1) return geodesicCirclePolygon(near[0].lat, near[0].lon, Math.min(swathKm / 2, 30));
    return null;
  }
  return clipPolygonToAoiCoverage(poly, target, swathKm);
}
