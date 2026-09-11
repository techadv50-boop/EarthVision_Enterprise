/** Build a closed imaging-corridor polygon around a ground-track segment. */

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
