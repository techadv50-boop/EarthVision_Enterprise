/** Lightweight geodesic helpers (no turf dependency). */

const R = 6371000; // Earth radius meters

function toRad(d: number): number {
  return (d * Math.PI) / 180;
}

export function haversineMeters(
  lon1: number,
  lat1: number,
  lon2: number,
  lat2: number,
): number {
  const φ1 = toRad(lat1);
  const φ2 = toRad(lat2);
  const Δφ = toRad(lat2 - lat1);
  const Δλ = toRad(lon2 - lon1);
  const a =
    Math.sin(Δφ / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

export function pathLengthMeters(coords: Array<[number, number]>): number {
  let sum = 0;
  for (let i = 1; i < coords.length; i++) {
    sum += haversineMeters(coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1]);
  }
  return sum;
}

/** Spherical polygon area (m²) via spherical excess. coords = [lon,lat][], ring closed. */
export function polygonAreaSqMeters(coords: Array<[number, number]>): number {
  if (coords.length < 3) return 0;
  const ring = [...coords];
  if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) {
    ring.push(ring[0]);
  }
  let total = 0;
  for (let i = 0; i < ring.length - 1; i++) {
    const [lon1, lat1] = ring[i];
    const [lon2, lat2] = ring[i + 1];
    total += toRad(lon2 - lon1) * (2 + Math.sin(toRad(lat1)) + Math.sin(toRad(lat2)));
  }
  return Math.abs((total * R * R) / 2);
}

export function formatDistance(meters: number): string {
  if (meters >= 1000) return `${(meters / 1000).toFixed(2)} km`;
  return `${meters.toFixed(0)} m`;
}

export function formatArea(sqMeters: number): string {
  if (sqMeters >= 1_000_000) return `${(sqMeters / 1_000_000).toFixed(2)} km²`;
  if (sqMeters >= 10_000) return `${(sqMeters / 10_000).toFixed(2)} ha`;
  return `${sqMeters.toFixed(0)} m²`;
}

export function bboxFromRing(ring: Array<[number, number]>): [number, number, number, number] {
  const lons = ring.map((c) => c[0]);
  const lats = ring.map((c) => c[1]);
  return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
}

export function footprintBbox(
  footprint: GeoJSON.Geometry | null | undefined,
  fallback?: [number, number, number, number],
): [number, number, number, number] | null {
  if (footprint && footprint.type === 'Polygon' && footprint.coordinates?.[0]) {
    return bboxFromRing(footprint.coordinates[0].map((c) => [c[0], c[1]]));
  }
  return fallback ?? null;
}
