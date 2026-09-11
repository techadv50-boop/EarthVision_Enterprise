import { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import {
  Check,
  Circle,
  MapPin,
  Navigation,
  Pentagon,
  Ruler,
  Square,
  Trash2,
} from 'lucide-react';
import { formatArea, formatLength, pathLengthKm, polygonAreaKm2 } from './measure';

export type MeasureTool = 'navigate' | 'distance' | 'polygon' | 'rectangle' | 'circle' | 'marker';

const TOOLS: { id: MeasureTool; icon: typeof Ruler; label: string; hint: string }[] = [
  { id: 'navigate', icon: Navigation, label: 'Pan', hint: 'Pan and zoom the map' },
  { id: 'distance', icon: Ruler, label: 'Distance', hint: 'Click points · double-click or Finish' },
  { id: 'polygon', icon: Pentagon, label: 'Area', hint: 'Click vertices · double-click or Finish' },
  { id: 'rectangle', icon: Square, label: 'Rectangle', hint: 'Click two opposite corners' },
  { id: 'circle', icon: Circle, label: 'Circle', hint: 'Click center, then the edge' },
  { id: 'marker', icon: MapPin, label: 'Marker', hint: 'Click to drop a coordinate marker' },
];

const DRAW = {
  color: '#22d3ee',
  weight: 2,
  fillColor: '#22d3ee',
  fillOpacity: 0.18,
  dashArray: undefined as string | undefined,
  interactive: false,
};

function labelIcon(text: string) {
  return L.divIcon({
    className: '',
    iconSize: [0, 0],
    html: `<div style="position:absolute;transform:translate(-50%,-120%);white-space:nowrap;background:#0b1622ee;color:#e2e8f0;border:1px solid #22d3ee88;border-radius:4px;padding:2px 6px;font:600 11px Inter,sans-serif;pointer-events:none">${text}</div>`,
  });
}

function vertexIcon() {
  return L.divIcon({
    className: '',
    iconSize: [10, 10],
    iconAnchor: [5, 5],
    html: `<span style="display:block;width:10px;height:10px;border-radius:50%;background:#22d3ee;border:2px solid #fff;box-shadow:0 0 4px #22d3ee"></span>`,
  });
}

function ll(p: L.LatLng) {
  return { lat: p.lat, lon: p.lng };
}

export default function MapMeasureTools({ map }: { map: L.Map | null }) {
  const [tool, setTool] = useState<MeasureTool>('navigate');
  const [hint, setHint] = useState(TOOLS[0].hint);
  const [readout, setReadout] = useState('');
  const [vertexCount, setVertexCount] = useState(0);
  const groupRef = useRef<L.LayerGroup | null>(null);
  const draftRef = useRef<L.Layer[]>([]);
  const previewRef = useRef<L.Layer | null>(null);
  const pointsRef = useRef<L.LatLng[]>([]);
  const toolRef = useRef(tool);
  const lastClickAt = useRef(0);
  const finishRef = useRef<() => void>(() => undefined);
  toolRef.current = tool;

  const clearDraft = () => {
    const g = groupRef.current;
    for (const l of draftRef.current) g?.removeLayer(l);
    if (previewRef.current) g?.removeLayer(previewRef.current);
    draftRef.current = [];
    previewRef.current = null;
    pointsRef.current = [];
    setVertexCount(0);
  };

  const addDraft = (layer: L.Layer) => {
    draftRef.current.push(layer);
    groupRef.current?.addLayer(layer);
    return layer;
  };

  useEffect(() => {
    if (!map) return;
    const g = L.layerGroup().addTo(map);
    groupRef.current = g;
    return () => {
      map.removeLayer(g);
      groupRef.current = null;
      draftRef.current = [];
      pointsRef.current = [];
    };
  }, [map]);

  useEffect(() => {
    if (!map) return;
    const drawing = tool !== 'navigate';
    map.dragging[drawing ? 'disable' : 'enable']();
    map.doubleClickZoom[drawing ? 'disable' : 'enable']();
    const el = map.getContainer();
    el.style.cursor = drawing ? 'crosshair' : '';
    setHint(TOOLS.find((t) => t.id === tool)?.hint || '');
    clearDraft();
    lastClickAt.current = 0;

    const addVertex = (latlng: L.LatLng) => {
      const t = toolRef.current;
      const pts = pointsRef.current;
      pts.push(latlng);
      addDraft(L.marker(latlng, { icon: vertexIcon(), interactive: false }));
      setVertexCount(pts.length);
      if (t === 'distance' && pts.length >= 2) {
        const last = pts[pts.length - 2];
        addDraft(L.polyline([last, latlng], { ...DRAW, dashArray: '6 4' }));
        setReadout(formatLength(pathLengthKm(pts.map(ll))));
      }
      if (t === 'polygon' && pts.length >= 2) {
        setReadout(
          pts.length >= 3
            ? formatArea(polygonAreaKm2(pts.map(ll)))
            : formatLength(pathLengthKm(pts.map(ll))),
        );
      }
    };

    const finishPoly = () => {
      const t = toolRef.current;
      const pts = [...pointsRef.current];
      if (t === 'distance' && pts.length >= 2) {
        clearDraft();
        const line = L.polyline(pts, DRAW);
        const len = formatLength(pathLengthKm(pts.map(ll)));
        groupRef.current?.addLayer(line);
        groupRef.current?.addLayer(
          L.marker(pts[pts.length - 1], { icon: labelIcon(len), interactive: false }),
        );
        setReadout(`Distance ${len}`);
      } else if (t === 'polygon' && pts.length >= 3) {
        clearDraft();
        const poly = L.polygon(pts, DRAW);
        const area = formatArea(polygonAreaKm2(pts.map(ll)));
        const peri = formatLength(pathLengthKm([...pts.map(ll), ll(pts[0])]));
        const label = `${area} · peri ${peri}`;
        groupRef.current?.addLayer(poly);
        groupRef.current?.addLayer(
          L.marker(poly.getBounds().getCenter(), { icon: labelIcon(label), interactive: false }),
        );
        setReadout(`Area ${label}`);
      }
    };
    finishRef.current = finishPoly;

    const onClick = (e: L.LeafletMouseEvent) => {
      const t = toolRef.current;
      const pts = pointsRef.current;
      if (t === 'navigate') return;
      L.DomEvent.stopPropagation(e);

      const now = performance.now();
      const isDbl = now - lastClickAt.current < 350;
      lastClickAt.current = now;

      if (t === 'distance' || t === 'polygon') {
        const last = pts[pts.length - 1];
        if (last && last.distanceTo(e.latlng) < 40) {
          if (isDbl) finishPoly();
          return;
        }
        addVertex(e.latlng);
        return;
      }

      if (t === 'marker') {
        const m = L.marker(e.latlng, { icon: vertexIcon() }).bindPopup(
          `${e.latlng.lat.toFixed(5)}°, ${e.latlng.lng.toFixed(5)}°`,
        );
        groupRef.current?.addLayer(m);
        m.openPopup();
        setReadout(`${e.latlng.lat.toFixed(5)}°, ${e.latlng.lng.toFixed(5)}°`);
        return;
      }

      if (t === 'rectangle' || t === 'circle') {
        if (pts.length === 0) {
          pts.push(e.latlng);
          addDraft(L.marker(e.latlng, { icon: vertexIcon(), interactive: false }));
          setVertexCount(1);
          return;
        }
        const a = pts[0];
        const b = e.latlng;
        clearDraft();
        if (t === 'rectangle') {
          const bounds = L.latLngBounds(a, b);
          const rect = L.rectangle(bounds, DRAW);
          const sw = bounds.getSouthWest();
          const ne = bounds.getNorthEast();
          const nw = L.latLng(ne.lat, sw.lng);
          const se = L.latLng(sw.lat, ne.lng);
          const ring = [ll(sw), ll(se), ll(ne), ll(nw)];
          const area = formatArea(polygonAreaKm2(ring));
          const w = formatLength(pathLengthKm([ll(sw), ll(se)]));
          const h = formatLength(pathLengthKm([ll(sw), ll(nw)]));
          const label = `${area} · ${w} × ${h}`;
          groupRef.current?.addLayer(rect);
          groupRef.current?.addLayer(
            L.marker(bounds.getCenter(), { icon: labelIcon(label), interactive: false }),
          );
          setReadout(`Rectangle ${label}`);
        } else {
          const rKm = pathLengthKm([ll(a), ll(b)]);
          const circ = L.circle(a, { ...DRAW, radius: rKm * 1000 });
          const area = formatArea(Math.PI * rKm * rKm);
          const label = `r ${formatLength(rKm)} · ${area}`;
          groupRef.current?.addLayer(circ);
          groupRef.current?.addLayer(L.marker(a, { icon: labelIcon(label), interactive: false }));
          setReadout(`Circle ${label}`);
        }
      }
    };

    const onMove = (e: L.LeafletMouseEvent) => {
      const t = toolRef.current;
      const pts = pointsRef.current;
      if (!pts.length || t === 'navigate' || t === 'marker') return;
      if (previewRef.current) {
        groupRef.current?.removeLayer(previewRef.current);
        previewRef.current = null;
      }
      let layer: L.Layer | null = null;
      if (t === 'distance' || t === 'polygon') {
        layer = L.polyline([...pts, e.latlng], { ...DRAW, dashArray: '4 4', weight: 1.5 });
      } else if (t === 'rectangle') {
        layer = L.rectangle(L.latLngBounds(pts[0], e.latlng), { ...DRAW, dashArray: '4 4' });
      } else if (t === 'circle') {
        const rKm = pathLengthKm([ll(pts[0]), ll(e.latlng)]);
        layer = L.circle(pts[0], { ...DRAW, radius: rKm * 1000, dashArray: '4 4' });
      }
      if (layer) {
        previewRef.current = layer;
        groupRef.current?.addLayer(layer);
      }
    };

    const onDbl = (e: L.LeafletMouseEvent) => {
      if (toolRef.current === 'distance' || toolRef.current === 'polygon') {
        L.DomEvent.stop(e);
        if (pointsRef.current.length === 0) return;
        const last = pointsRef.current[pointsRef.current.length - 1];
        if (!last || last.distanceTo(e.latlng) > 40) addVertex(e.latlng);
        finishPoly();
      }
    };

    const onKey = (ev: KeyboardEvent) => {
      const tag = (ev.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (ev.key === 'Escape') {
        clearDraft();
        setReadout('');
      }
      if (ev.key === 'Enter') finishPoly();
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
      map.dragging.enable();
      map.doubleClickZoom.enable();
      map.getContainer().style.cursor = '';
    };
  }, [map, tool]);

  const clearAll = () => {
    groupRef.current?.clearLayers();
    draftRef.current = [];
    pointsRef.current = [];
    setVertexCount(0);
    setReadout('');
  };

  const canFinish =
    (tool === 'distance' && vertexCount >= 2) || (tool === 'polygon' && vertexCount >= 3);

  return (
    <div className="pointer-events-none absolute left-2 top-[72px] z-[1100] flex flex-col items-start gap-1">
      <div className="pointer-events-auto flex w-9 flex-col gap-0.5 rounded bg-gray-950/90 p-1 ring-1 ring-white/10">
        {TOOLS.map(({ id, icon: Icon, label }) => (
          <button
            key={id}
            type="button"
            title={label}
            aria-label={label}
            onClick={() => setTool(id)}
            className={`rounded p-1.5 ${
              tool === id ? 'bg-cyan-600 text-white' : 'text-gray-400 hover:bg-white/10 hover:text-white'
            }`}
          >
            <Icon className="h-4 w-4" />
          </button>
        ))}
        {canFinish ? (
          <button
            type="button"
            title="Finish measurement"
            aria-label="Finish measurement"
            onClick={() => finishRef.current()}
            className="rounded p-1.5 text-cyan-300 hover:bg-cyan-600 hover:text-white"
          >
            <Check className="h-4 w-4" />
          </button>
        ) : null}
        <button
          type="button"
          title="Clear measurements"
          aria-label="Clear measurements"
          onClick={clearAll}
          className="rounded p-1.5 text-gray-400 hover:bg-white/10 hover:text-red-400"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
      {(readout || tool !== 'navigate') && (
        <div className="pointer-events-none max-w-[220px] rounded bg-gray-950/90 px-2 py-1 text-[10px] leading-snug text-gray-300 ring-1 ring-white/10">
          {readout ? <div className="font-medium text-cyan-300">{readout}</div> : null}
          {tool !== 'navigate' ? <div className="text-gray-500">{hint}</div> : null}
        </div>
      )}
    </div>
  );
}
