import { haversineKm } from './geometry';
import type { PredictTarget } from './types';

export interface PlaceHit {
  name: string;
  displayName: string;
  latitude: number;
  longitude: number;
  /** GeoJSON bbox [west, south, east, north] when the hit is a city/area. */
  boundingBox?: [number, number, number, number];
}

interface GazetteerPlace {
  name: string;
  aliases: string[];
  lat: number;
  lon: number;
  bbox: [number, number, number, number];
}

/** Offline fallback so city search still works if Nominatim is unreachable. */
const GAZETTEER: GazetteerPlace[] = [
  { name: 'Karachi', aliases: ['khi', 'karachi division'], lat: 24.8607, lon: 67.0011, bbox: [66.65, 24.72, 67.65, 25.2] },
  { name: 'Islamabad', aliases: ['isb'], lat: 33.6844, lon: 73.0479, bbox: [72.9, 33.55, 73.22, 33.82] },
  { name: 'Lahore', aliases: ['lhe'], lat: 31.5204, lon: 74.3587, bbox: [74.16, 31.38, 74.55, 31.7] },
  { name: 'Rawalpindi', aliases: [], lat: 33.5651, lon: 73.0169, bbox: [72.92, 33.5, 73.16, 33.7] },
  { name: 'Peshawar', aliases: [], lat: 34.0151, lon: 71.5249, bbox: [71.45, 33.95, 71.65, 34.08] },
  { name: 'Quetta', aliases: [], lat: 30.1798, lon: 66.975, bbox: [66.9, 30.1, 67.1, 30.28] },
  { name: 'Multan', aliases: [], lat: 30.1575, lon: 71.5249, bbox: [71.4, 30.08, 71.62, 30.28] },
  { name: 'Faisalabad', aliases: [], lat: 31.4504, lon: 73.135, bbox: [73.0, 31.35, 73.25, 31.55] },
  { name: 'Hyderabad', aliases: ['hyderabad pakistan'], lat: 25.396, lon: 68.3578, bbox: [68.28, 25.32, 68.45, 25.48] },
  { name: 'Dubai', aliases: ['dxb'], lat: 25.2048, lon: 55.2708, bbox: [55.05, 24.95, 55.6, 25.4] },
  { name: 'Riyadh', aliases: [], lat: 24.7136, lon: 46.6753, bbox: [46.4, 24.4, 47.0, 25.0] },
  { name: 'New Delhi', aliases: ['delhi'], lat: 28.6139, lon: 77.209, bbox: [76.84, 28.4, 77.35, 28.88] },
  { name: 'Mumbai', aliases: ['bombay'], lat: 19.076, lon: 72.8777, bbox: [72.77, 18.89, 73.0, 19.28] },
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
    boundingBox: p.bbox,
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
      const bbox = h.bounding_box;
      const box =
        bbox && bbox.length >= 4
          ? ([bbox[0], bbox[1], bbox[2], bbox[3]] as [number, number, number, number])
          : undefined;
      return {
        name: latinName(h.name || '', display),
        displayName: display,
        latitude: h.latitude,
        longitude: h.longitude,
        boundingBox: box,
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

function bboxDiagonalKm(b: [number, number, number, number]): number {
  return haversineKm(b[1], b[0], b[3], b[2]);
}

export function targetFromPlace(hit: PlaceHit): PredictTarget {
  const bbox = hit.boundingBox;
  if (bbox && bboxDiagonalKm(bbox) > 4 && bboxDiagonalKm(bbox) < 450) {
    const [w, s, e, n] = bbox;
    return {
      kind: 'area',
      name: hit.name,
      lat: hit.latitude,
      lon: hit.longitude,
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [w, s],
            [e, s],
            [e, n],
            [w, n],
            [w, s],
          ],
        ],
      },
    };
  }
  return {
    kind: 'point',
    name: hit.name,
    lat: hit.latitude,
    lon: hit.longitude,
    geometry: { type: 'Point', coordinates: [hit.longitude, hit.latitude] },
  };
}
