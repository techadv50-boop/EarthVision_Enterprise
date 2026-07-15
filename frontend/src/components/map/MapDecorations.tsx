import { useEffect, useState } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';

/** Leaflet lat/lon grid lines. */
export function LatLngGrid({ enabled = true }: { enabled?: boolean }) {
  const map = useMap();

  useEffect(() => {
    if (!enabled) return;

    const group = L.layerGroup().addTo(map);

    const draw = () => {
      group.clearLayers();
      const bounds = map.getBounds();
      const zoom = map.getZoom();
      const step = zoom < 5 ? 10 : zoom < 8 ? 5 : zoom < 11 ? 1 : zoom < 14 ? 0.25 : 0.1;

      const west = Math.floor(bounds.getWest() / step) * step;
      const east = Math.ceil(bounds.getEast() / step) * step;
      const south = Math.floor(bounds.getSouth() / step) * step;
      const north = Math.ceil(bounds.getNorth() / step) * step;

      for (let lon = west; lon <= east + 1e-9; lon += step) {
        L.polyline(
          [
            [south - step, lon],
            [north + step, lon],
          ],
          { color: '#64748b', weight: 0.6, opacity: 0.35, interactive: false },
        ).addTo(group);
      }
      for (let lat = south; lat <= north + 1e-9; lat += step) {
        L.polyline(
          [
            [lat, west - step],
            [lat, east + step],
          ],
          { color: '#64748b', weight: 0.6, opacity: 0.35, interactive: false },
        ).addTo(group);
      }
    };

    draw();
    map.on('moveend zoomend', draw);
    return () => {
      map.off('moveend zoomend', draw);
      group.remove();
    };
  }, [map, enabled]);

  return null;
}

/** Dynamic scale bar based on map center latitude and zoom. */
export function ScaleBar() {
  const map = useMap();
  const [label, setLabel] = useState('—');
  const [widthPx, setWidthPx] = useState(80);

  useEffect(() => {
    const update = () => {
      const y = map.getSize().y / 2;
      const maxWidthPx = 100;
      const left = map.containerPointToLatLng([0, y]);
      const right = map.containerPointToLatLng([maxWidthPx, y]);
      const meters = map.distance(left, right);
      const nice = niceLength(meters);
      const ratio = nice / meters;
      setWidthPx(Math.max(40, Math.round(maxWidthPx * ratio)));
      setLabel(formatMeters(nice));
    };
    update();
    map.on('moveend zoomend', update);
    return () => {
      map.off('moveend zoomend', update);
    };
  }, [map]);

  return (
    <div
      className="pointer-events-none absolute bottom-3 left-1/2 z-[1000] -translate-x-1/2 rounded-md border border-[var(--line)] bg-white/95 px-2 py-1 shadow-sm"
      data-map-chrome="scale"
    >
      <div className="mx-auto border-b-2 border-x-2 border-[var(--ink)]" style={{ width: widthPx, height: 8 }} />
      <div className="mt-0.5 text-center font-mono text-[10px] text-[var(--ink)]">{label}</div>
    </div>
  );
}

function niceLength(meters: number): number {
  const exponents = [1, 2, 5];
  const pow = Math.pow(10, Math.floor(Math.log10(meters)));
  for (const e of exponents) {
    const candidate = e * pow;
    if (candidate <= meters) return candidate;
  }
  return pow * 10;
}

function formatMeters(m: number): string {
  if (m >= 1000) return `${m / 1000} km`;
  return `${Math.round(m)} m`;
}

export function NorthArrow() {
  return (
    <div
      className="pointer-events-none absolute right-3 top-3 z-[1000] flex flex-col items-center rounded-lg border border-[var(--line)] bg-white/95 px-2 py-1.5 shadow-sm"
      data-map-chrome="north"
    >
      <svg width="28" height="36" viewBox="0 0 28 36" aria-label="North">
        <polygon points="14,2 22,18 14,14 6,18" fill="#1f6f54" />
        <polygon points="14,14 22,18 14,34 6,18" fill="#94a3b8" />
        <text x="14" y="12" textAnchor="middle" fontSize="8" fontWeight="700" fill="white">
          N
        </text>
      </svg>
    </div>
  );
}
