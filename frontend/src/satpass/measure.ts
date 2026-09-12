import { haversineKm } from './predict/geometry';

const R_KM = 6371;

export function pathLengthKm(pts: { lat: number; lon: number }[]): number {
  let n = 0;
  for (let i = 1; i < pts.length; i += 1) n += haversineKm(pts[i - 1].lat, pts[i - 1].lon, pts[i].lat, pts[i].lon);
  return n;
}

/** Spherical polygonal area (km²) using an equal-area trapezoid on the sphere. */
export function polygonAreaKm2(pts: { lat: number; lon: number }[]): number {
  if (pts.length < 3) return 0;
  const toRad = (d: number) => (d * Math.PI) / 180;
  let sum = 0;
  const n = pts.length;
  for (let i = 0; i < n; i += 1) {
    const j = (i + 1) % n;
    const λ1 = toRad(pts[i].lon);
    const λ2 = toRad(pts[j].lon);
    sum += (λ2 - λ1) * (2 + Math.sin(toRad(pts[i].lat)) + Math.sin(toRad(pts[j].lat)));
  }
  return Math.abs((sum * R_KM * R_KM) / 2);
}

export function formatLength(km: number): string {
  if (!Number.isFinite(km)) return '—';
  if (km < 1) return `${Math.round(km * 1000)} m`;
  if (km < 10) return `${km.toFixed(2)} km`;
  if (km < 100) return `${km.toFixed(1)} km`;
  return `${km.toFixed(0)} km`;
}

export function formatArea(km2: number): string {
  if (!Number.isFinite(km2)) return '—';
  if (km2 < 0.01) return `${Math.round(km2 * 1e6)} m²`;
  if (km2 < 1) return `${(km2 * 100).toFixed(1)} ha`;
  const digits = km2 >= 100 ? 0 : 2;
  return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(km2)} km²`;
}
