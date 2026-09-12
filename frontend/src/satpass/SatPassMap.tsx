import { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { parseTle, getState, groundTrack, footprintRadiusMeters, type SatState } from './orbit';
import { addBaseMap } from './baseMap';
import MapMeasureTools from './MapMeasureTools';
import type { SatRec } from 'satellite.js';

export interface TrackedSat {
  id: number;
  name: string;
  line1: string;
  line2: string;
  color: string;
  visible: boolean;
  swathKm: number;
  noradId?: number | null;
}

interface Props {
  sats: TrackedSat[];
  onStates?: (states: Record<number, SatState>) => void;
  focusId?: number | null;
  showVisibility?: boolean;
}

interface SatRuntime {
  satrec: SatRec;
  name: string;
  color: string;
  swathKm: number;
  marker: L.Marker;
  swath: L.Circle;
  vis: L.Circle;
  trackLayers: L.Polyline[];
}

function dotIcon(color: string) {
  return L.divIcon({
    className: 'satpass-dot',
    iconSize: [14, 14],
    iconAnchor: [7, 7],
    html: `<span style="display:block;width:12px;height:12px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 0 6px ${color}"></span>`,
  });
}

function setLayerVisible(map: L.Map, layer: L.Layer, visible: boolean) {
  if (visible && !map.hasLayer(layer)) layer.addTo(map);
  else if (!visible && map.hasLayer(layer)) map.removeLayer(layer);
}

export default function SatPassMap({ sats, onStates, focusId, showVisibility = false }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const [leafletMap, setLeafletMap] = useState<L.Map | null>(null);
  const runtimeRef = useRef<Map<number, SatRuntime>>(new Map());
  const onStatesRef = useRef(onStates);
  onStatesRef.current = onStates;
  const showVisRef = useRef(showVisibility);
  showVisRef.current = showVisibility;

  // Create the Leaflet map once (flat equirectangular world, offline vector base).
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      crs: L.CRS.EPSG4326,
      center: [20, 0],
      zoom: 1,
      minZoom: 0,
      maxZoom: 6,
      worldCopyJump: false,
      attributionControl: false,
      maxBounds: [
        [-90, -180],
        [90, 180],
      ],
      maxBoundsViscosity: 1,
    });
    mapRef.current = map;
    setLeafletMap(map);

    // Lightweight offline base map: bundled Natural Earth countries + labels.
    addBaseMap(map);

    // The map lives next to a sidebar; make sure Leaflet re-measures its box.
    const invalidate = () => map.invalidateSize();
    const raf = window.setTimeout(invalidate, 0);
    const resizeObserver =
      typeof ResizeObserver !== 'undefined' && containerRef.current
        ? new ResizeObserver(invalidate)
        : null;
    if (resizeObserver && containerRef.current) resizeObserver.observe(containerRef.current);
    window.addEventListener('resize', invalidate);

    let lastTrack = 0;
    const timer = window.setInterval(() => {
      const date = new Date();
      const runtime = runtimeRef.current;
      const states: Record<number, SatState> = {};
      const now = performance.now();
      const refreshTracks = now - lastTrack > 3000;
      if (refreshTracks) lastTrack = now;

      runtime.forEach((rt, id) => {
        const s = getState(rt.satrec, date);
        if (!s) return;
        states[id] = s;
        const ll = L.latLng(s.lat, s.lon);
        rt.marker.setLatLng(ll);
        rt.marker.setTooltipContent(
          `<b>${rt.name}</b><br>${s.lat.toFixed(2)}, ${s.lon.toFixed(2)} · ${s.altKm.toFixed(0)} km`,
        );
        rt.swath.setLatLng(ll);
        rt.vis.setLatLng(ll).setRadius(footprintRadiusMeters(s.altKm));
        if (refreshTracks && mapRef.current) refreshTrack(mapRef.current, rt, date);
      });
      onStatesRef.current?.(states);
    }, 1000);

    return () => {
      window.clearInterval(timer);
      window.clearTimeout(raf);
      window.removeEventListener('resize', invalidate);
      resizeObserver?.disconnect();
      map.remove();
      mapRef.current = null;
      setLeafletMap(null);
      runtimeRef.current.clear();
    };
  }, []);

  // Sync satellite layers with the tracked list.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const runtime = runtimeRef.current;
    const wanted = new Set(sats.map((s) => s.id));

    runtime.forEach((rt, id) => {
      if (!wanted.has(id)) {
        [rt.marker, rt.swath, rt.vis, ...rt.trackLayers].forEach((l) => map.removeLayer(l));
        runtime.delete(id);
      }
    });

    for (const sat of sats) {
      let rt = runtime.get(sat.id);
      if (!rt) {
        let satrec: SatRec;
        try {
          satrec = parseTle(sat.line1, sat.line2);
        } catch {
          continue;
        }
        const date = new Date();
        const s = getState(satrec, date);
        const ll = L.latLng(s?.lat ?? 0, s?.lon ?? 0);
        const marker = L.marker(ll, { icon: dotIcon(sat.color) }).bindTooltip(sat.name, {
          permanent: true,
          direction: 'top',
          offset: [0, -8],
          className: 'satpass-tip',
        });
        const swath = L.circle(ll, {
          radius: (sat.swathKm * 1000) / 2,
          color: sat.color,
          weight: 1,
          fillColor: sat.color,
          fillOpacity: 0.35,
        });
        const vis = L.circle(ll, {
          radius: s ? footprintRadiusMeters(s.altKm) : 0,
          color: sat.color,
          weight: 1,
          opacity: 0.4,
          fillColor: sat.color,
          fillOpacity: 0.08,
        });
        rt = {
          satrec,
          name: sat.name,
          color: sat.color,
          swathKm: sat.swathKm,
          marker,
          swath,
          vis,
          trackLayers: [],
        };
        runtime.set(sat.id, rt);
        refreshTrack(map, rt, date);
      }

      rt.name = sat.name;
      rt.swathKm = sat.swathKm;
      rt.swath.setRadius((sat.swathKm * 1000) / 2);

      setLayerVisible(map, rt.marker, sat.visible);
      setLayerVisible(map, rt.swath, sat.visible);
      rt.trackLayers.forEach((l) => setLayerVisible(map, l, sat.visible));
      setLayerVisible(map, rt.vis, sat.visible && showVisibility);
    }
  }, [sats, showVisibility]);

  // Fly to a satellite.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || focusId == null) return;
    const rt = runtimeRef.current.get(focusId);
    if (!rt) return;
    map.setView(rt.marker.getLatLng(), 3, { animate: true });
  }, [focusId]);

  return (
    <>
      <div ref={containerRef} className="absolute inset-0 h-full w-full" style={{ background: '#0b1622' }} />
      <MapMeasureTools map={leafletMap} />
    </>
  );
}

function refreshTrack(map: L.Map, rt: SatRuntime, date: Date) {
  const visible = rt.trackLayers.length ? map.hasLayer(rt.trackLayers[0]) : true;
  rt.trackLayers.forEach((l) => map.removeLayer(l));
  rt.trackLayers = [];
  const segments = groundTrack(rt.satrec, date);
  for (const seg of segments) {
    if (seg.length < 2) continue;
    const latlngs = seg.map((p) => L.latLng(p.lat, p.lon));
    const line = L.polyline(latlngs, { pane: 'overlayPane', color: rt.color, weight: 2, opacity: 0.85 });
    rt.trackLayers.push(line);
    if (visible) line.addTo(map);
  }
}
