import { getState, parseTle } from '../orbit';
import { haversineKm, minDistanceToGeometryKm, pointInPolygon } from '../predict/geometry';
import { knownSensor } from '../predict/catalog';
import { constellationOf, imagingSwathKm, type ActiveSat } from './catalog';

export type WatchRelation = 'overhead' | 'watching' | 'in-view';

export interface WatchHit {
  name: string;
  noradId: number | null;
  line1: string;
  line2: string;
  constellation: string;
  lat: number;
  lon: number;
  altKm: number;
  distanceKm: number;
  elevationDeg: number;
  relation: WatchRelation;
  swathKm: number | null;
}

const EARTH_KM = 6371;

function boundsOf(geom: GeoJSON.Geometry): { west: number; east: number; south: number; north: number } | null {
  let west = Infinity;
  let east = -Infinity;
  let south = Infinity;
  let north = -Infinity;
  let any = false;
  const take = (lon: number, lat: number) => {
    any = true;
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  };
  const walk = (g: GeoJSON.Geometry) => {
    if (g.type === 'Point') take(g.coordinates[0], g.coordinates[1]);
    else if (g.type === 'MultiPoint' || g.type === 'LineString') g.coordinates.forEach(([lon, lat]) => take(lon, lat));
    else if (g.type === 'MultiLineString' || g.type === 'Polygon') {
      g.coordinates.forEach((ring) => ring.forEach(([lon, lat]) => take(lon, lat)));
    } else if (g.type === 'MultiPolygon') {
      g.coordinates.forEach((poly) => poly.forEach((ring) => ring.forEach(([lon, lat]) => take(lon, lat))));
    } else if (g.type === 'GeometryCollection') g.geometries.forEach(walk);
  };
  walk(geom);
  return any ? { west, east, south, north } : null;
}

/** Geometric elevation of a satellite as seen from a ground point. */
export function elevationDeg(
  satLat: number,
  satLon: number,
  altKm: number,
  obsLat: number,
  obsLon: number,
): number {
  const central = haversineKm(satLat, satLon, obsLat, obsLon) / EARTH_KM;
  const ratio = EARTH_KM / (EARTH_KM + Math.max(altKm, 1));
  const el = Math.atan2(Math.cos(central) - ratio, Math.sin(central));
  return (el * 180) / Math.PI;
}

function rank(relation: WatchRelation): number {
  if (relation === 'overhead') return 0;
  if (relation === 'watching') return 1;
  return 2;
}

export function compareHits(a: WatchHit, b: WatchHit): number {
  const byRelation = rank(a.relation) - rank(b.relation);
  if (byRelation) return byRelation;
  return a.distanceKm - b.distanceKm;
}

/**
 * Which active satellites are over the area, cover it with an imaging swath,
 * or are simply above its horizon right now.
 */
export function scanSlice(sats: ActiveSat[], geometry: GeoJSON.Geometry, now: Date): WatchHit[] {
  const box = boundsOf(geometry);
  if (!box) return [];
  const midLat = (box.south + box.north) / 2;
  const midLon = (box.west + box.east) / 2;
  const hits: WatchHit[] = [];
  for (const sat of sats) {
    let state;
    try {
      state = getState(parseTle(sat.line1, sat.line2), now);
    } catch {
      continue;
    }
    if (!state) continue;
    // Anything outside this window is below the horizon for the area.
    if (state.lat < box.south - 35 || state.lat > box.north + 35) continue;
    if (state.lon < box.west - 35 || state.lon > box.east + 35) continue;

    const swathKm = imagingSwathKm(sat.name, knownSensor(sat.name, sat.noradId)?.swathKm ?? null);
    const nearLat = Math.min(box.north, Math.max(box.south, state.lat));
    const nearLon = Math.min(box.east, Math.max(box.west, state.lon));
    const roughKm = haversineKm(state.lat, state.lon, nearLat, nearLon);
    const observerLat = roughKm === 0 ? midLat : nearLat;
    const observerLon = roughKm === 0 ? midLon : nearLon;
    const el = elevationDeg(state.lat, state.lon, state.altKm, observerLat, observerLon);
    if (el < 0 && roughKm > 0) continue;

    const nearShape =
      state.lat >= box.south - 3 &&
      state.lat <= box.north + 3 &&
      state.lon >= box.west - 3 &&
      state.lon <= box.east + 3;
    const inside = nearShape && pointInPolygon(state.lat, state.lon, geometry);
    let distanceKm = roughKm;
    if (inside) distanceKm = 0;
    else if (roughKm === 0 || (swathKm != null && roughKm <= swathKm / 2 + 300)) {
      distanceKm = minDistanceToGeometryKm(state.lat, state.lon, geometry);
    }

    let relation: WatchRelation | null = null;
    if (inside || distanceKm === 0) relation = 'overhead';
    else if (swathKm != null && distanceKm <= swathKm / 2) relation = 'watching';
    else if (el >= 0) relation = 'in-view';
    if (!relation) continue;

    hits.push({
      name: sat.name,
      noradId: sat.noradId,
      line1: sat.line1,
      line2: sat.line2,
      constellation: constellationOf(sat.name),
      lat: state.lat,
      lon: state.lon,
      altKm: state.altKm,
      distanceKm,
      elevationDeg: el,
      relation,
      swathKm,
    });
  }
  return hits;
}

export async function scanActive(
  sats: ActiveSat[],
  geometry: GeoJSON.Geometry,
  now: Date,
  onProgress?: (done: number, total: number, hits: WatchHit[]) => void,
  cancelled?: () => boolean,
): Promise<WatchHit[]> {
  const hits: WatchHit[] = [];
  const step = 400;
  for (let i = 0; i < sats.length; i += step) {
    if (cancelled?.()) return hits.sort(compareHits);
    hits.push(...scanSlice(sats.slice(i, i + step), geometry, now));
    hits.sort(compareHits);
    onProgress?.(Math.min(i + step, sats.length), sats.length, hits);
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  return hits;
}
