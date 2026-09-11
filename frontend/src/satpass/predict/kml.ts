/** Parse KML coordinates "lon,lat[,alt] lon,lat..." into [lon, lat][]. */
function parseCoords(text: string): number[][] {
  return text
    .trim()
    .split(/[\s\n]+/)
    .map((t) => t.trim())
    .filter(Boolean)
    .map((t) => t.split(',').map(Number))
    .filter((p) => p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]))
    .map((p) => [p[0], p[1]]);
}

function localName(el: Element): string {
  return (el.localName || el.tagName || '').replace(/^.*:/, '').toLowerCase();
}

function child(el: Element, name: string): Element | undefined {
  return [...el.children].find((c) => localName(c) === name);
}

function all(el: Element, name: string): Element[] {
  return [...el.getElementsByTagName('*')].filter((c) => localName(c) === name) as Element[];
}

function geometryFromPlacemark(pm: Element): GeoJSON.Geometry | null {
  const point = child(pm, 'point');
  if (point) {
    const c = parseCoords(child(point, 'coordinates')?.textContent || '');
    if (c[0]) return { type: 'Point', coordinates: c[0] };
  }
  const line = child(pm, 'linestring');
  if (line) {
    const c = parseCoords(child(line, 'coordinates')?.textContent || '');
    if (c.length >= 2) return { type: 'LineString', coordinates: c };
  }
  const poly = child(pm, 'polygon');
  if (poly) {
    const outer = child(poly, 'outerboundaryis') || poly;
    const coordsEl = all(outer, 'coordinates')[0];
    const ring = parseCoords(coordsEl?.textContent || '');
    if (ring.length >= 4) {
      if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) {
        ring.push(ring[0]);
      }
      return { type: 'Polygon', coordinates: [ring] };
    }
  }
  return null;
}

export function parseKmlToGeoJSON(kmlText: string): GeoJSON.FeatureCollection {
  const doc = new DOMParser().parseFromString(kmlText, 'text/xml');
  const features: GeoJSON.Feature[] = [];
  for (const pm of all(doc.documentElement, 'placemark')) {
    const geom = geometryFromPlacemark(pm);
    if (!geom) continue;
    const name = child(pm, 'name')?.textContent?.trim() || '';
    features.push({ type: 'Feature', properties: { name }, geometry: geom });
  }
  return { type: 'FeatureCollection', features };
}
