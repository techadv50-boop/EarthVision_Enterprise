import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { addBaseMap, createSatPassMap } from './baseMap';
import type { PredictResult, PredictTarget } from './predict/types';

interface Props {
  target: PredictTarget | null;
  result: PredictResult | null;
  hiddenSats: Set<string>;
  showLabels: boolean;
  showTarget: boolean;
  onCursor?: (text: string) => void;
}

function timeIcon(text: string, color: string) {
  return L.divIcon({
    className: '',
    iconSize: [0, 0],
    html: `<div style="position:absolute;transform:translate(-50%,-110%);white-space:nowrap;pointer-events:none;color:${color};font:600 10px Inter,sans-serif;text-shadow:0 1px 2px #000">${text}</div>`,
  });
}

function splitLon(samples: { lat: number; lon: number }[]) {
  const segs: { lat: number; lon: number }[][] = [];
  let cur: { lat: number; lon: number }[] = [];
  let prev: number | null = null;
  for (const s of samples) {
    if (prev !== null && Math.abs(s.lon - prev) > 180) {
      if (cur.length) segs.push(cur);
      cur = [];
    }
    cur.push(s);
    prev = s.lon;
  }
  if (cur.length) segs.push(cur);
  return segs;
}

export default function PredictMap({
  target,
  result,
  hiddenSats,
  showLabels,
  showTarget,
  onCursor,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const overlayRef = useRef<L.LayerGroup | null>(null);
  const fittedRef = useRef<PredictResult | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = createSatPassMap(containerRef.current);
    mapRef.current = map;
    addBaseMap(map);
    overlayRef.current = L.layerGroup().addTo(map);
    const onMove = (e: L.LeafletMouseEvent) => {
      onCursor?.(`${e.latlng.lat.toFixed(4)}°, ${e.latlng.lng.toFixed(4)}°`);
    };
    map.on('mousemove', onMove);
    const invalidate = () => map.invalidateSize();
    const raf = window.setTimeout(invalidate, 0);
    const ro = new ResizeObserver(invalidate);
    ro.observe(containerRef.current);
    return () => {
      map.off('mousemove', onMove);
      window.clearTimeout(raf);
      ro.disconnect();
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
  }, [onCursor]);

  useEffect(() => {
    const map = mapRef.current;
    const overlay = overlayRef.current;
    if (!map || !overlay) return;
    overlay.clearLayers();
    const bounds: L.LatLng[] = [];

    if (target && showTarget) {
      const layer = L.geoJSON(target.geometry as GeoJSON.GeoJsonObject, {
        pointToLayer: (_f, latlng) =>
          L.circleMarker(latlng, {
            radius: 7,
            color: '#fbbf24',
            fillColor: '#fbbf24',
            fillOpacity: 0.9,
            weight: 2,
          }),
        style: {
          color: '#fbbf24',
          weight: 2,
          fillColor: '#fbbf24',
          fillOpacity: 0.2,
        },
      }).bindTooltip(target.name, { sticky: true });
      overlay.addLayer(layer);
      layer.eachLayer((l) => {
        if (l instanceof L.Marker || l instanceof L.CircleMarker) bounds.push(l.getLatLng());
        else if ('getBounds' in l) {
          const b = (l as L.Polygon).getBounds();
          bounds.push(b.getSouthWest(), b.getNorthEast());
        }
      });
    }

    for (const track of result?.tracks || []) {
      if (hiddenSats.has(track.satelliteId) || hiddenSats.has(track.satelliteName)) continue;
      for (const seg of splitLon(track.samples)) {
        if (seg.length < 2) continue;
        const line = L.polyline(
          seg.map((p) => L.latLng(p.lat, p.lon)),
          { color: track.color, weight: 2.5, opacity: 0.95 },
        );
        overlay.addLayer(line);
        bounds.push(...seg.map((p) => L.latLng(p.lat, p.lon)));
      }
      if (showLabels) {
        for (const lab of track.labels) {
          overlay.addLayer(
            L.marker([lab.lat, lab.lon], {
              interactive: false,
              icon: timeIcon(lab.text, track.color),
            }),
          );
        }
      }
    }

    if (bounds.length && result !== fittedRef.current) {
      map.fitBounds(L.latLngBounds(bounds), { padding: [24, 24], maxZoom: 6 });
      fittedRef.current = result;
    }
  }, [target, result, hiddenSats, showLabels, showTarget]);

  return (
    <div ref={containerRef} className="absolute inset-0 h-full w-full" style={{ background: '#0b1622' }} />
  );
}
