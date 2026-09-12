import { DEFAULT_TARGET_BUFFER_KM, geodesicCirclePolygon } from './geometry';
import type { PredictTarget } from './types';

export { DEFAULT_TARGET_BUFFER_KM };

export interface PlaceHit {
  name: string;
  displayName: string;
  latitude: number;
  longitude: number;
}

interface GazetteerPlace {
  name: string;
  aliases: string[];
  lat: number;
  lon: number;
}

/** Offline fallback so city search still works if Nominatim is unreachable. */
const GAZETTEER: GazetteerPlace[] = [
  { name: 'Karachi', aliases: ['khi', 'karachi division'], lat: 24.8607, lon: 67.0011 },
  { name: 'Islamabad', aliases: ['isb'], lat: 33.6844, lon: 73.0479 },
  { name: 'Lahore', aliases: ['lhe'], lat: 31.5204, lon: 74.3587 },
  { name: 'Rawalpindi', aliases: ['pindi'], lat: 33.5651, lon: 73.0169 },
  { name: 'Gwadar', aliases: ['gwadar port'], lat: 25.1264, lon: 62.3225 },
  { name: 'Peshawar', aliases: [], lat: 34.0151, lon: 71.5249 },
  { name: 'Quetta', aliases: [], lat: 30.1798, lon: 66.975 },
  { name: 'Multan', aliases: [], lat: 30.1575, lon: 71.5249 },
  { name: 'Faisalabad', aliases: [], lat: 31.4504, lon: 73.135 },
  { name: 'Hyderabad', aliases: ['hyderabad pakistan'], lat: 25.396, lon: 68.3578 },
  { name: 'Dubai', aliases: ['dxb'], lat: 25.2048, lon: 55.2708 },
  { name: 'Riyadh', aliases: [], lat: 24.7136, lon: 46.6753 },
  { name: 'New Delhi', aliases: ['delhi'], lat: 28.6139, lon: 77.209 },
  { name: 'Mumbai', aliases: ['bombay'], lat: 19.076, lon: 72.8777 },
];

function latinName(name: string, displayName: string): string {
  if (name && /^[\x20-\x7E]/.test(name) && /[A-Za-z]/.test(name)) return name;
  const head = (displayName || '').split(',')[0]?.trim();
  return head || name || 'Place';
}

export function lookupGazetteer(query: string): PlaceHit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return GAZETTEER.filter(
    (p) =>
      p.name.toLowerCase() === q ||
      p.aliases.some((a) => a === q) ||
      p.name.toLowerCase().startsWith(q) ||
      p.aliases.some((a) => a.startsWith(q)),
  ).map((p) => ({
    name: p.name,
    displayName: p.name,
    latitude: p.lat,
    longitude: p.lon,
  }));
}

export function normalizeGeoHits(
  raw: { name?: string; display_name?: string; latitude: number; longitude: number; bounding_box?: number[] | null }[],
  query: string,
): PlaceHit[] {
  return raw
    .filter((h) => Number.isFinite(h.latitude) && Number.isFinite(h.longitude))
    .map((h) => {
      const display = h.display_name || h.name || query;
      return {
        name: latinName(h.name || '', display),
        displayName: display,
        latitude: h.latitude,
        longitude: h.longitude,
      };
    });
}

export function mergePlaceHits(primary: PlaceHit[], extra: PlaceHit[]): PlaceHit[] {
  const out: PlaceHit[] = [];
  const seen = new Set<string>();
  for (const h of [...primary, ...extra]) {
    const key = `${h.latitude.toFixed(3)},${h.longitude.toFixed(3)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(h);
  }
  return out;
}

/** Named place → lat/lng point + geodesic 20 km (default) target AOI. */
export function targetFromPlace(hit: PlaceHit, bufferKm = DEFAULT_TARGET_BUFFER_KM): PredictTarget {
  const km = bufferKm > 0 ? bufferKm : DEFAULT_TARGET_BUFFER_KM;
  return {
    kind: 'area',
    name: hit.name,
    lat: hit.latitude,
    lon: hit.longitude,
    bufferKm: km,
    source: 'place',
    geometry: geodesicCirclePolygon(hit.latitude, hit.longitude, km),
  };
}

export function targetFromLatLon(
  lat: number,
  lon: number,
  name: string,
  bufferKm = DEFAULT_TARGET_BUFFER_KM,
): PredictTarget {
  const km = bufferKm > 0 ? bufferKm : DEFAULT_TARGET_BUFFER_KM;
  return {
    kind: 'area',
    name: name || 'Point',
    lat,
    lon,
    bufferKm: km,
    source: 'coordinates',
    geometry: geodesicCirclePolygon(lat, lon, km),
  };
}
