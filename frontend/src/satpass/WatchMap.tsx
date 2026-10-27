import { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { addBaseMap, createSatPassMap } from './baseMap';
import type { WatchHit } from './watch/scan';

interface Props {
  adminGeojson: GeoJSON.FeatureCollection | null;
  selectedName: string | null;
  hits: WatchHit[];
  onArea: (feature: GeoJSON.Feature) => void;
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

export default function WatchMap({ adminGeojson, selectedName, hits, onArea }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const areasRef = useRef<L.GeoJSON | null>(null);
  const marksRef = useRef<L.LayerGroup | null>(null);
  const onAreaRef = useRef(onArea);
  onAreaRef.current = onArea;
  const selectedRef = useRef(selectedName);
  selectedRef.current = selectedName;
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = createSatPassMap(containerRef.current);
    map.setMaxZoom(8);
    mapRef.current = map;
    areasRef.current = L.geoJSON(undefined, { pane: 'overlayPane' }).addTo(map);
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
      marksRef.current = null;
      setReady(false);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const areas = areasRef.current;
    if (!map || !areas || !ready) return;
    areas.clearLayers();
    if (!adminGeojson?.features?.length) return;
    const layer = L.geoJSON(adminGeojson as GeoJSON.GeoJsonObject, {
      pane: 'overlayPane',
      style: (feat) => boundaryStyle(featureName(feat as GeoJSON.Feature), selectedRef.current),
      onEachFeature: (feat, shape) => {
        const name = featureName(feat as GeoJSON.Feature) || 'Area';
        shape.bindTooltip(name, { sticky: true });
        shape.on('click', (ev) => {
          L.DomEvent.stopPropagation(ev);
          onAreaRef.current(feat as GeoJSON.Feature);
        });
      },
    });
    layer.eachLayer((child) => areas.addLayer(child));
    const bounds = layer.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [28, 28], maxZoom: 6, animate: false });
  }, [adminGeojson, ready]);

  useEffect(() => {
    const areas = areasRef.current;
    if (!areas || !ready) return;
    areas.eachLayer((layer) => {
      const path = layer as L.Path & { feature?: GeoJSON.Feature };
      if (!path.setStyle || !path.feature) return;
      path.setStyle(boundaryStyle(featureName(path.feature), selectedName));
    });
  }, [selectedName, ready, adminGeojson]);

  useEffect(() => {
    const marks = marksRef.current;
    if (!marks || !ready) return;
    marks.clearLayers();
    const plotted = hits.filter((hit) => hit.relation === 'overhead' || hit.relation === 'watching').slice(0, 80);
    for (const hit of plotted) {
      const color = markerColor(hit.relation);
      const marker = L.circleMarker([hit.lat, hit.lon], {
        pane: 'markerPane',
        radius: hit.relation === 'overhead' ? 6 : 4,
        color,
        weight: 2,
        fillColor: color,
        fillOpacity: 0.9,
      });
      marker.bindTooltip(
        `${hit.name}<br>${hit.constellation} · ${hit.relation === 'overhead' ? 'Over the area' : 'Swath covers the area'}`,
        { direction: 'top', offset: [0, -4] },
      );
      marks.addLayer(marker);
    }
  }, [hits, ready]);

  return <div ref={containerRef} className="absolute inset-0 h-full w-full" style={{ background: '#0b1622' }} />;
}
