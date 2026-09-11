const R_KM = 6371;

export function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R_KM * Math.asin(Math.min(1, Math.sqrt(a)));
}

function pointInRing(lat: number, lon: number, ring: number[][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const intersect = yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi + 1e-12) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

function polygonsFromGeometry(geom: GeoJSON.Geometry): number[][][][] {
  if (geom.type === 'Polygon') return [geom.coordinates as number[][][]];
  if (geom.type === 'MultiPolygon') return geom.coordinates as number[][][][];
  if (geom.type === 'GeometryCollection') {
    return geom.geometries.flatMap((g) => polygonsFromGeometry(g));
  }
  return [];
}

export function pointInPolygon(lat: number, lon: number, geom: GeoJSON.Geometry): boolean {
  for (const poly of polygonsFromGeometry(geom)) {
    if (!poly.length) continue;
    if (!pointInRing(lat, lon, poly[0])) continue;
    let inHole = false;
    for (let h = 1; h < poly.length; h += 1) {
      if (pointInRing(lat, lon, poly[h])) inHole = true;
    }
    if (!inHole) return true;
  }
  return false;
}

function distPointToSegmentKm(
  lat: number,
  lon: number,
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const n = 8;
  let best = Infinity;
  for (let i = 0; i <= n; i += 1) {
    const t = i / n;
    const la = lat1 + (lat2 - lat1) * t;
    const lo = lon1 + (lon2 - lon1) * t;
    best = Math.min(best, haversineKm(lat, lon, la, lo));
  }
  return best;
}

/** Minimum distance from a lat/lon to a polygon (0 if inside). */
export function minDistanceToGeometryKm(lat: number, lon: number, geom: GeoJSON.Geometry): number {
  if (geom.type === 'Point') {
    const [plo, pla] = geom.coordinates;
    return haversineKm(lat, lon, pla, plo);
  }
  if (geom.type === 'MultiPoint') {
    return Math.min(...geom.coordinates.map(([plo, pla]) => haversineKm(lat, lon, pla, plo)));
  }
  if (pointInPolygon(lat, lon, geom)) return 0;
  let best = Infinity;
  for (const poly of polygonsFromGeometry(geom)) {
    const ring = poly[0] || [];
    for (let i = 0; i < ring.length - 1; i += 1) {
      best = Math.min(
        best,
        distPointToSegmentKm(lat, lon, ring[i][1], ring[i][0], ring[i + 1][1], ring[i + 1][0]),
      );
    }
  }
  return best;
}

export function centroidOfGeometry(geom: GeoJSON.Geometry): { lon: number; lat: number } | null {
  if (geom.type === 'Point') {
    return { lon: geom.coordinates[0], lat: geom.coordinates[1] };
  }
  const pts: number[][] = [];
  const walk = (g: GeoJSON.Geometry) => {
    if (g.type === 'Point') pts.push(g.coordinates);
    else if (g.type === 'MultiPoint' || g.type === 'LineString') pts.push(...g.coordinates);
    else if (g.type === 'MultiLineString' || g.type === 'Polygon') g.coordinates.forEach((r) => pts.push(...r));
    else if (g.type === 'MultiPolygon') g.coordinates.forEach((p) => p.forEach((r) => pts.push(...r)));
    else if (g.type === 'GeometryCollection') g.geometries.forEach(walk);
  };
  walk(geom);
  if (!pts.length) return null;
  const lon = pts.reduce((s, p) => s + p[0], 0) / pts.length;
  const lat = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  return { lon, lat };
}

export function geometryKind(geom: GeoJSON.Geometry): 'point' | 'area' {
  if (geom.type === 'Point' || geom.type === 'MultiPoint') return 'point';
  return 'area';
}
