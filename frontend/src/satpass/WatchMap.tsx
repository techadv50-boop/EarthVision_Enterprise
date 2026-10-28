import { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { addBaseMap, createSatPassMap } from './baseMap';
import { compassPoint } from './orbit';
import { destinationPoint } from './predict/footprint';
import type { WatchHit } from './watch/scan';

export type WatchLayerRole = 'select' | 'guide-country' | 'guide-province';

export interface WatchLayer {
  role: WatchLayerRole;
  data: GeoJSON.FeatureCollection;
}

export interface WatchTrackLine {
  key: string;
  name: string;
  color: string;
  segments: { lat: number; lon: number }[][];
}

export interface WatchTrackMotion {
  key: string;
  name: string;
  color: string;
  lat: number;
  lon: number;
  altKm: number;
  speedKmS: number;
  headingDeg: number | null;
}

interface Props {
  layers: WatchLayer[];
  selectedName: string | null;
  guideName: string | null;
  hits: WatchHit[];
  onArea: (feature: GeoJSON.Feature) => void;
  onSat: (hit: WatchHit) => void;
  onTrackKey: (key: string) => void;
  trackedKeys: string[];
  trackLines: WatchTrackLine[];
  trackMotion: WatchTrackMotion[];
}

function markerColor(relation: WatchHit['relation']): string {
  if (relation === 'overhead') return '#fbbf24';
  if (relation === 'watching') return '#22d3ee';
  return '#94a3b8';
}

function featureName(feature: GeoJSON.Feature | undefined): string {
  return String((feature?.properties as { name?: string } | null)?.name || '');
}

function boundaryStyle(name: string, selectedName: string | null): L.PathOptions {
  const on = Boolean(selectedName && name === selectedName);
  return {
    color: on ? '#fbbf24' : '#67e8f9',
    weight: on ? 2.5 : 1,
    fillColor: on ? '#fbbf24' : '#155e75',
    fillOpacity: on ? 0.38 : 0.16,
  };
}

function layerStyle(role: WatchLayerRole, name: string, selectedName: string | null, guideName: string | null): L.PathOptions {
  if (role === 'guide-country') {
    return { color: '#e2e8f0', weight: 1.8, opacity: 0.9, fillOpacity: 0 };
  }
  if (role === 'guide-province') {
    const on = Boolean(guideName && name === guideName);
    return {
      color: on ? '#fbbf24' : '#38bdf8',
      weight: on ? 2.2 : 1,
      opacity: 0.95,
      fillOpacity: 0,
    };
  }
  return boundaryStyle(name, selectedName);
}

export default function WatchMap({
  layers,
  selectedName,
  guideName,
  hits,
  onArea,
  onSat,
  onTrackKey,
  trackedKeys,
  trackLines,
  trackMotion,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const areasRef = useRef<L.GeoJSON | null>(null);
  const marksRef = useRef<L.LayerGroup | null>(null);
  const tracksRef = useRef<L.LayerGroup | null>(null);
  const motionRef = useRef<L.LayerGroup | null>(null);
  const onAreaRef = useRef(onArea);
  onAreaRef.current = onArea;
  const onSatRef = useRef(onSat);
  onSatRef.current = onSat;
  const onTrackKeyRef = useRef(onTrackKey);
  onTrackKeyRef.current = onTrackKey;
  const selectedRef = useRef(selectedName);
  selectedRef.current = selectedName;
  const guideRef = useRef(guideName);
  guideRef.current = guideName;
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = createSatPassMap(containerRef.current);
    map.setMaxZoom(8);
    mapRef.current = map;
    areasRef.current = L.geoJSON(undefined, { pane: 'overlayPane' }).addTo(map);
    tracksRef.current = L.layerGroup().addTo(map);
    motionRef.current = L.layerGroup().addTo(map);
    marksRef.current = L.layerGroup().addTo(map);
    addBaseMap(map);
    setReady(true);
    const invalidate = () => map.invalidateSize();
    const t1 = window.setTimeout(invalidate, 50);
    const t2 = window.setTimeout(invalidate, 250);
    const ro = new ResizeObserver(invalidate);
    ro.observe(containerRef.current);
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
      ro.disconnect();
      map.remove();
      mapRef.current = null;
      areasRef.current = null;
      tracksRef.current = null;
      motionRef.current = null;
      marksRef.current = null;
      setReady(false);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const areas = areasRef.current;
    if (!map || !areas || !ready) return;
    areas.clearLayers();
    let focus: L.GeoJSON | null = null;
    for (const entry of layers) {
      if (!entry.data.features.length) continue;
      const layer = L.geoJSON(entry.data as GeoJSON.GeoJsonObject, {
        pane: 'overlayPane',
        interactive: true,
        style: (feat) =>
          layerStyle(entry.role, featureName(feat as GeoJSON.Feature), selectedRef.current, guideRef.current),
        onEachFeature: (feat, shape) => {
          const feature = feat as GeoJSON.Feature;
          const name = featureName(feature) || 'Area';
          shape.bindTooltip(name, { sticky: true });
          (shape as L.Path & { feature?: GeoJSON.Feature; watchRole?: WatchLayerRole }).feature = feature;
          (shape as L.Path & { watchRole?: WatchLayerRole }).watchRole = entry.role;
          shape.on('click', (ev) => {
            L.DomEvent.stopPropagation(ev);
            onAreaRef.current(feature);
          });
        },
      });
      layer.eachLayer((child) => areas.addLayer(child));
      if (entry.data.features.length) focus = layer;
    }
    if (focus) {
      const bounds = focus.getBounds();
      if (bounds.isValid()) map.fitBounds(bounds, { padding: [28, 28], maxZoom: 6, animate: false });
    }
  }, [layers, ready]);

  useEffect(() => {
    const areas = areasRef.current;
    if (!areas || !ready) return;
    areas.eachLayer((layer) => {
      const path = layer as L.Path & { feature?: GeoJSON.Feature; watchRole?: WatchLayerRole };
      if (!path.setStyle || !path.feature || !path.watchRole) return;
      path.setStyle(layerStyle(path.watchRole, featureName(path.feature), selectedName, guideName));
    });
  }, [selectedName, guideName, ready, layers]);

  useEffect(() => {
    const tracks = tracksRef.current;
    if (!tracks || !ready) return;
    tracks.clearLayers();
    for (const line of trackLines) {
      for (const segment of line.segments) {
        if (segment.length < 2) continue;
        tracks.addLayer(
          L.polyline(
            segment.map((point) => L.latLng(point.lat, point.lon)),
            { pane: 'overlayPane', color: line.color, weight: 2.5, opacity: 0.95 },
          ),
        );
      }
    }
  }, [trackLines, ready]);

  useEffect(() => {
    const motionLayer = motionRef.current;
    if (!motionLayer || !ready) return;
    motionLayer.clearLayers();
    for (const motion of trackMotion) {
      const here = L.latLng(motion.lat, motion.lon);
      const heading =
        motion.headingDeg == null
          ? ''
          : `<br>${motion.speedKmS.toFixed(2)} km/s · heading ${motion.headingDeg.toFixed(0)}° ${compassPoint(motion.headingDeg)}`;
      const satMarker = L.circleMarker(here, {
        pane: 'markerPane',
        radius: 7,
        color: '#fff',
        weight: 2,
        fillColor: motion.color,
        fillOpacity: 1,
      }).bindTooltip(
        `<b>${motion.name}</b><br>${motion.lat.toFixed(2)}, ${motion.lon.toFixed(2)} · ${motion.altKm.toFixed(0)} km${heading}<br>Click to hide this track`,
        { permanent: true, direction: 'top', offset: [0, -8] },
      );
      satMarker.on('click', (ev) => {
        L.DomEvent.stopPropagation(ev);
        onTrackKeyRef.current(motion.key);
      });
      motionLayer.addLayer(satMarker);
      const satEl = satMarker.getElement() as SVGElement | undefined;
      if (satEl) satEl.style.cursor = 'pointer';
      if (motion.headingDeg != null) {
        const tip = destinationPoint(motion.lat, motion.lon, motion.headingDeg, Math.max(180, motion.altKm * 0.2));
        motionLayer.addLayer(
          L.polyline([here, L.latLng(tip.lat, tip.lon)], {
            pane: 'overlayPane',
            color: motion.color,
            weight: 3,
            opacity: 1,
          }),
        );
      }
    }
  }, [trackMotion, ready]);

  useEffect(() => {
    const marks = marksRef.current;
    if (!marks || !ready) return;
    marks.clearLayers();
    const plotted = hits.filter((hit) => hit.relation === 'overhead' || hit.relation === 'watching');
    const tracked = new Set(trackedKeys);
    for (const hit of plotted) {
      const key = hit.noradId != null ? `n${hit.noradId}` : hit.line1;
      const on = tracked.has(key);
      const color = markerColor(hit.relation);
      const marker = L.circleMarker([hit.lat, hit.lon], {
        pane: 'markerPane',
        radius: hit.relation === 'overhead' ? 6 : 4,
        color: on ? '#fff' : color,
        weight: on ? 3 : 2,
        fillColor: color,
        fillOpacity: 0.9,
      });
      marker.bindTooltip(
        `${hit.name}<br>${hit.constellation} · ${hit.relation === 'overhead' ? 'Over the area' : 'Swath covers the area'}<br>${on ? 'Click to hide this track' : 'Click to show this track'}`,
        { direction: 'top', offset: [0, -4] },
      );
      marker.on('click', (ev) => {
        L.DomEvent.stopPropagation(ev);
        onSatRef.current(hit);
      });
      marks.addLayer(marker);
      const el = marker.getElement() as SVGElement | undefined;
      if (el) el.style.cursor = 'pointer';
    }
  }, [hits, trackedKeys, ready]);

  return <div ref={containerRef} className="absolute inset-0 h-full w-full" style={{ background: '#0b1622' }} />;
}
