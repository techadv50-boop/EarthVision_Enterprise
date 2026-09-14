import L from 'leaflet';

const OCEANS: { name: string; lat: number; lon: number }[] = [
  { name: 'NORTH PACIFIC OCEAN', lat: 25, lon: -160 },
  { name: 'SOUTH PACIFIC OCEAN', lat: -30, lon: -125 },
  { name: 'NORTH ATLANTIC OCEAN', lat: 32, lon: -42 },
  { name: 'SOUTH ATLANTIC OCEAN', lat: -30, lon: -18 },
  { name: 'INDIAN OCEAN', lat: -22, lon: 78 },
  { name: 'SOUTHERN OCEAN', lat: -62, lon: 40 },
  { name: 'ARCTIC OCEAN', lat: 80, lon: 0 },
];

function textIcon(text: string, style: string) {
  return L.divIcon({
    className: '',
    iconSize: [0, 0],
    html: `<div style="position:absolute;transform:translate(-50%,-50%);white-space:nowrap;pointer-events:none;${style}">${text}</div>`,
  });
}

/** Keep country fills under tracks even when the GeoJSON arrives late. */
export function ensureBaseMapPanes(map: L.Map) {
  if (!map.getPane('basemapPane')) {
    const pane = map.createPane('basemapPane');
    pane.style.zIndex = '250';
    pane.style.pointerEvents = 'none';
  }
  if (!map.getPane('basemapLabelsPane')) {
    const pane = map.createPane('basemapLabelsPane');
    pane.style.zIndex = '260';
    pane.style.pointerEvents = 'none';
  }
  const overlay = map.getPane('overlayPane');
  if (overlay) overlay.style.zIndex = '450';
  const marker = map.getPane('markerPane');
  if (marker) marker.style.zIndex = '600';
}

/** Offline Natural Earth countries + labels used by Track and Predict maps. */
export function addBaseMap(map: L.Map) {
  ensureBaseMapPanes(map);
  fetch('/world-countries-110m.geojson')
    .then((r) => r.json())
    .then((geo: GeoJSON.FeatureCollection) => {
      L.geoJSON(geo, {
        pane: 'basemapPane',
        interactive: false,
        style: {
          color: '#3d5670',
          weight: 0.8,
          fillColor: '#1c2c3d',
          fillOpacity: 1,
        },
      }).addTo(map);

      for (const f of geo.features) {
        const p = (f.properties || {}) as Record<string, unknown>;
        const rank = Number(p.LABELRANK);
        const lon = Number(p.LABEL_X);
        const lat = Number(p.LABEL_Y);
        const name = String(p.NAME ?? '');
        if (!name || Number.isNaN(lon) || Number.isNaN(lat) || rank > 2) continue;
        L.marker([lat, lon], {
          pane: 'basemapLabelsPane',
          interactive: false,
          keyboard: false,
          icon: textIcon(
            name.toUpperCase(),
            'color:#c7d4e0;font:600 10px Inter,sans-serif;letter-spacing:0.5px;text-shadow:0 1px 2px #000',
          ),
        }).addTo(map);
      }

      for (const o of OCEANS) {
        L.marker([o.lat, o.lon], {
          pane: 'basemapLabelsPane',
          interactive: false,
          keyboard: false,
          icon: textIcon(
            o.name,
            'color:#5b86ad;font:italic 500 11px Inter,sans-serif;letter-spacing:1px;opacity:0.8',
          ),
        }).addTo(map);
      }
    })
    .catch(() => undefined);
}

export function createSatPassMap(container: HTMLElement): L.Map {
  const map = L.map(container, {
    crs: L.CRS.EPSG4326,
    center: [20, 0],
    zoom: 2,
    minZoom: 0,
    maxZoom: 8,
    worldCopyJump: false,
    attributionControl: false,
    maxBounds: [
      [-90, -180],
      [90, 180],
    ],
    maxBoundsViscosity: 1,
  });
  ensureBaseMapPanes(map);
  return map;
}
