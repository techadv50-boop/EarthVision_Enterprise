import { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { addBaseMap, createSatPassMap } from './baseMap';
import MapMeasureTools from './MapMeasureTools';
import type { PassRow, PredictResult, PredictTarget } from './predict/types';
import { formatPassPopup, leafletDashArray } from './predict/catalog';
import { durationLabel, formatInZone, formatUtc } from './predict/time';

interface Props {
  target: PredictTarget | null;
  result: PredictResult | null;
  hiddenSats: Set<string>;
  hiddenPasses: Set<string>;
  showLabels: boolean;
  showTarget: boolean;
  showFootprints: boolean;
  timeZone: string;
  onCursor?: (text: string) => void;
}

function timeIcon(text: string, color: string, side: 'left' | 'right') {
  const shift = side === 'left' ? 'translate(-108%,-50%)' : 'translate(8%,-50%)';
  return L.divIcon({
    className: '',
    iconSize: [0, 0],
    html: `<div style="position:absolute;transform:${shift};white-space:nowrap;pointer-events:none;color:${color};font:600 10px Inter,sans-serif;background:rgba(7,12,18,.78);padding:1px 5px;border-radius:3px;border:1px solid ${color}66">${text}</div>`,
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

function popupHtml(pass: PassRow | undefined, timeZone: string, fallback: string): string {
  if (!pass) return fallback;
  return formatPassPopup(pass, timeZone, {
    zone: formatInZone,
    utc: formatUtc,
    duration: durationLabel,
  });
}

export default function PredictMap({
  target,
  result,
  hiddenSats,
  hiddenPasses,
  showLabels,
  showTarget,
  showFootprints,
  timeZone,
  onCursor,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const overlayRef = useRef<L.LayerGroup | null>(null);
  const fittedKeyRef = useRef<string>('');
  const lastFitRef = useRef<{ bounds: L.LatLngBounds; maxZoom: number } | null>(null);
  const [leafletMap, setLeafletMap] = useState<L.Map | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = createSatPassMap(containerRef.current);
    map.setMaxZoom(8);
    mapRef.current = map;
    fittedKeyRef.current = '';
    lastFitRef.current = null;
    setLeafletMap(map);
    addBaseMap(map);
    overlayRef.current = L.layerGroup().addTo(map);
    const onMove = (e: L.LeafletMouseEvent) => {
      onCursor?.(`${e.latlng.lat.toFixed(4)}°, ${e.latlng.lng.toFixed(4)}°`);
    };
    map.on('mousemove', onMove);
    const applyStoredFit = () => {
      map.invalidateSize();
      const stored = lastFitRef.current;
      const size = map.getSize();
      if (!stored || size.x < 80 || size.y < 80) return;
      const c = stored.bounds.getCenter();
      map.setView(c, stored.maxZoom, { animate: false });
      map.fitBounds(stored.bounds, { padding: [40, 40], maxZoom: stored.maxZoom, animate: false });
    };
    const raf = window.setTimeout(applyStoredFit, 50);
    const ro = new ResizeObserver(applyStoredFit);
    ro.observe(containerRef.current);
    return () => {
      map.off('mousemove', onMove);
      window.clearTimeout(raf);
      ro.disconnect();
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
      lastFitRef.current = null;
      setLeafletMap(null);
    };
  }, [onCursor]);

  useEffect(() => {
    const map = mapRef.current;
    const overlay = overlayRef.current;
    if (!map || !overlay) return;
    overlay.clearLayers();
    const passById = new Map((result?.passes || []).map((p) => [p.passId, p]));

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
          weight: 3,
          fillColor: '#fbbf24',
          fillOpacity: 0.35,
        },
      }).bindTooltip(target.name, { sticky: true, permanent: true, direction: 'top', offset: [0, -8] });
      overlay.addLayer(layer);
    }

    for (const track of result?.tracks || []) {
      if (hiddenSats.has(track.satelliteId) || hiddenPasses.has(track.passId)) continue;
      const pass = passById.get(track.passId);
      const dash = leafletDashArray(track.dash);
      const html = popupHtml(pass, timeZone, `${track.satelliteName} ${track.passId}`);
      const fillOpacity = 0.16 + ((pass?.passNumber ?? 1) % 3) * 0.05;
      const trackOpacity = pass?.imagingEligible === false ? 0.55 : 0.95;

      if (showFootprints && track.footprint) {
        const poly = L.geoJSON(track.footprint as GeoJSON.GeoJsonObject, {
          style: {
            color: track.color,
            weight: 2,
            dashArray: dash,
            fillColor: track.color,
            fillOpacity,
          },
        });
        poly.bindPopup(html);
        poly.bindTooltip(track.passId, { sticky: true, opacity: 0.9 });
        overlay.addLayer(poly);
      }

      for (const seg of splitLon(track.samples)) {
        if (seg.length < 2) continue;
        const line = L.polyline(
          seg.map((p) => L.latLng(p.lat, p.lon)),
          { color: track.color, weight: 2.5, opacity: trackOpacity, dashArray: dash },
        );
        line.bindPopup(html);
        overlay.addLayer(line);
      }

      if (showLabels) {
        const side = (pass?.passNumber ?? 1) % 2 === 0 ? 'right' : 'left';
        for (const lab of track.labels) {
          overlay.addLayer(
            L.marker([lab.lat, lab.lon], {
              interactive: false,
              icon: timeIcon(`${lab.text}`, track.color, side),
            }),
          );
        }
      }
    }

    const fitKey = `${target?.kind}:${target?.name}:${target?.lat}:${target?.lon}:${target?.bufferKm ?? ''}:${result?.passes.map((p) => p.passId).join(',') || 'none'}`;
    if (target && fitKey !== fittedKeyRef.current) {
      const pts: L.LatLng[] = [];
      const gb = L.geoJSON(target.geometry as GeoJSON.GeoJsonObject).getBounds();
      if (gb.isValid()) {
        pts.push(gb.getSouthWest(), gb.getNorthEast());
      } else {
        pts.push(L.latLng(target.lat, target.lon));
      }
      for (const track of result?.tracks || []) {
        if (hiddenSats.has(track.satelliteId) || hiddenPasses.has(track.passId)) continue;
        for (const s of track.samples) pts.push(L.latLng(s.lat, s.lon));
      }
      if (pts.length) {
        const bounds = L.latLngBounds(pts);
        const hasTrack = (result?.tracks || []).some(
          (tr) => !hiddenSats.has(tr.satelliteId) && !hiddenPasses.has(tr.passId),
        );
        const maxZoom = hasTrack ? 4 : 8;
        const padded = bounds.pad(hasTrack ? 0.08 : 0.35);
        lastFitRef.current = { bounds: padded, maxZoom };
        const apply = () => {
          map.invalidateSize();
          const size = map.getSize();
          if (size.x < 80 || size.y < 80) return;
          map.fitBounds(padded, { padding: [28, 28], maxZoom, animate: false });
        };
        apply();
        window.setTimeout(apply, 80);
        window.setTimeout(apply, 250);
      }
      fittedKeyRef.current = fitKey;
    }
  }, [target, result, hiddenSats, hiddenPasses, showLabels, showTarget, showFootprints, timeZone, leafletMap]);

  return (
    <>
      <div ref={containerRef} className="absolute inset-0 h-full w-full" style={{ background: '#0b1622' }} />
      <MapMeasureTools map={leafletMap} />
    </>
  );
}
