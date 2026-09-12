import { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { addBaseMap, createSatPassMap } from './baseMap';
import MapMeasureTools from './MapMeasureTools';
import type { PassRow, PredictResult, PredictTarget } from './predict/types';
import { formatPassPopup, leafletDashArray } from './predict/catalog';
import { durationLabel, formatInZone, formatUtc } from './predict/time';
import { targetFromLatLon } from './predict/places';
import { targetFromGeometry } from './predict/passes';

export type AoiDrawMode = 'off' | 'point' | 'polygon';

interface Props {
  target: PredictTarget | null;
  result: PredictResult | null;
  hiddenSats: Set<string>;
  hiddenPasses: Set<string>;
  showLabels: boolean;
  showTarget: boolean;
  showFootprints: boolean;
  timeZone: string;
  aoiDraw?: AoiDrawMode;
  bufferKm?: number;
  aoiName?: string;
  onCursor?: (text: string) => void;
  onAoiDrawn?: (target: PredictTarget) => void;
  onAoiCancel?: () => void;
}

function ringFromLatLngs(pts: L.LatLng[]): GeoJSON.Polygon {
  const ring: [number, number][] = pts.map((p) => [p.lng, p.lat]);
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first && last && (first[0] !== last[0] || first[1] !== last[1])) ring.push([first[0], first[1]]);
  return { type: 'Polygon', coordinates: [ring] };
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
  aoiDraw = 'off',
  bufferKm = 20,
  aoiName = '',
  onCursor,
  onAoiDrawn,
  onAoiCancel,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const overlayRef = useRef<L.LayerGroup | null>(null);
  const fittedKeyRef = useRef<string>('');
  const lastFitRef = useRef<{ bounds: L.LatLngBounds; maxZoom: number } | null>(null);
  const finishPolyRef = useRef<() => void>(() => undefined);
  const onAoiDrawnRef = useRef(onAoiDrawn);
  const onAoiCancelRef = useRef(onAoiCancel);
  onAoiDrawnRef.current = onAoiDrawn;
  onAoiCancelRef.current = onAoiCancel;
  const [leafletMap, setLeafletMap] = useState<L.Map | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = createSatPassMap(containerRef.current);
    map.setMaxZoom(12);
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

    const visibleTracks = (result?.tracks || []).filter(
      (tr) => !hiddenSats.has(tr.satelliteId) && !hiddenPasses.has(tr.passId),
    );
    const labeledPassId = visibleTracks[0]?.passId;

    for (const track of visibleTracks) {
      const pass = passById.get(track.passId);
      const dash = leafletDashArray(track.dash);
      const html = popupHtml(pass, timeZone, `${track.satelliteName} ${track.passId}`);
      const fillOpacity = 0.22 + ((pass?.passNumber ?? 1) % 3) * 0.06;
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

      if (showLabels && track.passId === labeledPassId) {
        for (const lab of track.labels) {
          overlay.addLayer(
            L.marker([lab.lat, lab.lon], {
              interactive: false,
              icon: timeIcon(`${lab.text}`, track.color, 'right'),
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
        for (const s of track.samples) {
          if (Math.abs(s.lat) > 78) continue;
          let lon = s.lon;
          let d = lon - target.lon;
          while (d > 180) {
            lon -= 360;
            d = lon - target.lon;
          }
          while (d < -180) {
            lon += 360;
            d = lon - target.lon;
          }
          if (Math.abs(d) > 42) continue;
          pts.push(L.latLng(s.lat, lon));
        }
      }
      if (pts.length) {
        const hasTrack = (result?.tracks || []).some(
          (tr) => !hiddenSats.has(tr.satelliteId) && !hiddenPasses.has(tr.passId),
        );
        const bounds = hasTrack
          ? L.latLngBounds(
              [85, Math.min(...pts.map((p) => p.lng), target.lon) - 6],
              [-85, Math.max(...pts.map((p) => p.lng), target.lon) + 6],
            )
          : L.latLngBounds(pts);
        const maxZoom = hasTrack ? 3 : 8;
        const padded = bounds.pad(hasTrack ? 0.02 : 0.35);
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

  useEffect(() => {
    const map = mapRef.current;
    if (!map || aoiDraw === 'off') return;
    const draft = L.layerGroup().addTo(map);
    const pts: L.LatLng[] = [];
    let preview: L.Layer | null = null;
    map.dragging.disable();
    map.doubleClickZoom.disable();
    map.getContainer().style.cursor = 'crosshair';

    const vertex = () =>
      L.divIcon({
        className: '',
        iconSize: [10, 10],
        iconAnchor: [5, 5],
        html: `<span style="display:block;width:10px;height:10px;border-radius:50%;background:#fbbf24;border:2px solid #fff"></span>`,
      });

    const clearPreview = () => {
      if (preview) {
        draft.removeLayer(preview);
        preview = null;
      }
    };

    const finishPolygon = () => {
      if (pts.length < 3) return;
      const geom = ringFromLatLngs(pts);
      const t = targetFromGeometry(geom, aoiName.trim() || 'Drawn AOI');
      if (t) onAoiDrawnRef.current?.({ ...t, source: 'map' });
    };
    finishPolyRef.current = finishPolygon;

    const onClick = (e: L.LeafletMouseEvent) => {
      L.DomEvent.stopPropagation(e);
      if (aoiDraw === 'point') {
        onAoiDrawnRef.current?.(
          targetFromLatLon(e.latlng.lat, e.latlng.lng, aoiName.trim() || 'Map point', bufferKm),
        );
        return;
      }
      pts.push(e.latlng);
      draft.addLayer(L.marker(e.latlng, { icon: vertex(), interactive: false }));
      if (pts.length >= 2) {
        draft.addLayer(L.polyline(pts, { color: '#fbbf24', weight: 2, dashArray: '4 4' }));
      }
    };

    const onMove = (e: L.LeafletMouseEvent) => {
      if (aoiDraw !== 'polygon' || !pts.length) return;
      clearPreview();
      preview = L.polyline([...pts, e.latlng], { color: '#fbbf24', weight: 1.5, dashArray: '3 4' });
      draft.addLayer(preview);
    };

    const onDbl = (e: L.LeafletMouseEvent) => {
      if (aoiDraw !== 'polygon') return;
      L.DomEvent.stop(e);
      if (pts.length && pts[pts.length - 1].distanceTo(e.latlng) > 40) pts.push(e.latlng);
      finishPolygon();
    };

    const onKey = (ev: KeyboardEvent) => {
      const tag = (ev.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (ev.key === 'Escape') onAoiCancelRef.current?.();
      if (ev.key === 'Enter' && aoiDraw === 'polygon') finishPolygon();
    };

    map.on('click', onClick);
    map.on('mousemove', onMove);
    map.on('dblclick', onDbl);
    window.addEventListener('keydown', onKey);
    return () => {
      map.off('click', onClick);
      map.off('mousemove', onMove);
      map.off('dblclick', onDbl);
      window.removeEventListener('keydown', onKey);
      map.removeLayer(draft);
      map.dragging.enable();
      map.doubleClickZoom.enable();
      map.getContainer().style.cursor = '';
    };
  }, [leafletMap, aoiDraw, bufferKm, aoiName]);

  const drawing = aoiDraw !== 'off';

  return (
    <>
      <div ref={containerRef} className="absolute inset-0 h-full w-full" style={{ background: '#0b1622' }} />
      <MapMeasureTools map={leafletMap} disabled={drawing} />
      {drawing ? (
        <div className="pointer-events-auto absolute bottom-3 left-1/2 z-[1100] flex -translate-x-1/2 items-center gap-2 rounded bg-gray-950/90 px-3 py-1.5 text-[11px] text-amber-200 ring-1 ring-amber-500/40">
          <span>
            {aoiDraw === 'point'
              ? 'Click anywhere on the globe to place a point AOI'
              : 'Click vertices · double-click or Finish to close · Esc to cancel'}
          </span>
          {aoiDraw === 'polygon' ? (
            <button
              type="button"
              onClick={() => finishPolyRef.current()}
              className="rounded bg-amber-500 px-2 py-0.5 font-medium text-black hover:bg-amber-400"
            >
              Finish
            </button>
          ) : null}
          <button
            type="button"
            onClick={onAoiCancel}
            className="rounded bg-white/10 px-2 py-0.5 text-gray-200 hover:bg-white/20"
          >
            Cancel
          </button>
        </div>
      ) : null}
    </>
  );
}
