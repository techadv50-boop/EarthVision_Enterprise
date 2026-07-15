import { useEffect, useMemo, useRef, useState, Fragment, type Dispatch, type SetStateAction } from 'react';
import {
  MapContainer,
  TileLayer,
  Marker,
  CircleMarker,
  Polyline,
  Polygon,
  Rectangle,
  ImageOverlay,
  useMap,
  useMapEvents,
  GeoJSON,
} from 'react-leaflet';
import L from 'leaflet';
import type { PlaceSelection, MapTool, MapOverlay, DrawnFeature } from '../store/workflowStore';
import {
  formatArea,
  formatDistance,
  pathLengthMeters,
  polygonAreaSqMeters,
} from '../utils/geoMath';
import { LatLngGrid, NorthArrow, ScaleBar } from '../components/map/MapDecorations';
import { DemTerrainLayer, isArcSceneMode } from './DemTerrainLayer';
import 'leaflet/dist/leaflet.css';

type LonLat = [number, number]; // [lon, lat]
type LatLon = [number, number]; // [lat, lon] for Leaflet

const markerIcon = L.icon({
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});

interface Props {
  place: PlaceSelection | null;
  overlays: MapOverlay[];
  mapTool: MapTool;
  aoiGeoJson: GeoJSON.Feature | null;
  drawnFeature: DrawnFeature | null;
  bufferGeoJson: GeoJSON.Polygon | null;
  enablePlaceClick: boolean;
  showGrid?: boolean;
  mapChrome?: {
    compass?: boolean;
    scaleBar?: boolean;
    coordinates?: boolean;
    miniMap?: boolean;
    swipe?: boolean;
    view3d?: boolean;
    rotate?: boolean;
    terrainRelief?: boolean;
  };
  mapCommand?: { id: number; type: string } | null;
  onPlaceClick: (lon: number, lat: number) => void;
  onAoiComplete: (feature: GeoJSON.Feature) => void;
  onDrawnFeature: (feature: DrawnFeature) => void;
  onMeasure: (label: string | null) => void;
}

function toLatLon(pts: LonLat[]): LatLon[] {
  return pts.map(([lon, lat]) => [lat, lon]);
}

function MapCommandRunner({
  command,
}: {
  command: { id: number; type: string } | null | undefined;
}) {
  const map = useMap();
  useEffect(() => {
    if (!command) return;
    if (command.type === 'zoom-in') map.zoomIn();
    if (command.type === 'zoom-out') map.zoomOut();
    if (command.type === 'fullscreen') {
      const el = map.getContainer().closest('#ev-map-host') as HTMLElement | null;
      if (!el) return;
      if (document.fullscreenElement) void document.exitFullscreen();
      else void el.requestFullscreen?.();
    }
  }, [command, map]);
  return null;
}

function CursorCoordinates({ enabled }: { enabled: boolean }) {
  const [pos, setPos] = useState<string>('—');
  useMapEvents({
    mousemove(e) {
      if (!enabled) return;
      setPos(`${e.latlng.lat.toFixed(5)}°, ${e.latlng.lng.toFixed(5)}°`);
    },
  });
  if (!enabled) return null;
  return (
    <div className="pointer-events-none absolute bottom-3 left-1/2 z-[1000] -translate-x-1/2 rounded-full border border-[var(--line)] bg-white/95 px-3 py-1 font-mono text-[11px] shadow">
      {pos}
    </div>
  );
}

function MiniMapPanel({ enabled }: { enabled: boolean }) {
  const map = useMap();
  const [center, setCenter] = useState(() => map.getCenter());
  useEffect(() => {
    if (!enabled) return;
    const sync = () => setCenter(map.getCenter());
    map.on('moveend', sync);
    return () => {
      map.off('moveend', sync);
    };
  }, [map, enabled]);
  if (!enabled) return null;
  return (
    <div className="pointer-events-none absolute bottom-14 right-3 z-[1000] h-28 w-36 overflow-hidden rounded-lg border border-[var(--line)] bg-white/95 shadow">
      <div className="border-b border-[var(--line)] px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-[var(--muted)]">
        Mini map
      </div>
      <div className="flex h-[calc(100%-18px)] items-center justify-center bg-[#dce8e2] font-mono text-[10px] text-[var(--muted)]">
        {center.lat.toFixed(2)}, {center.lng.toFixed(2)}
      </div>
    </div>
  );
}

function SwipeMask({ enabled, overlays }: { enabled: boolean; overlays: MapOverlay[] }) {
  const [pct, setPct] = useState(50);
  if (!enabled) return null;
  const scenes = overlays.filter((o) => o.kind === 'scene' && o.visible !== false);
  if (scenes.length < 2) {
    return (
      <div className="pointer-events-none absolute top-16 left-1/2 z-[1000] -translate-x-1/2 rounded-full bg-white/95 px-3 py-1 text-[11px] text-[var(--muted)] shadow">
        Swipe needs 2+ visible scenes
      </div>
    );
  }
  return (
    <div className="pointer-events-auto absolute inset-x-0 bottom-20 z-[1000] flex justify-center px-6">
      <label className="flex w-full max-w-md items-center gap-2 rounded-xl border border-[var(--line)] bg-white/95 px-3 py-2 text-[11px] shadow">
        Swipe
        <input
          type="range"
          min={5}
          max={95}
          value={pct}
          onChange={(e) => setPct(Number(e.target.value))}
          className="w-full accent-[var(--accent)]"
        />
        <span className="font-mono">{pct}%</span>
      </label>
      <div
        className="pointer-events-none absolute inset-y-0 left-0 border-r-2 border-[var(--accent)]"
        style={{ width: `${pct}%`, top: '-40vh', height: '80vh' }}
      />
    </div>
  );
}

function FlyToPlace({ place }: { place: PlaceSelection | null }) {
  const map = useMap();
  useEffect(() => {
    if (!place) return;
    const [west, south, east, north] = place.bbox;
    map.fitBounds(
      [
        [south, west],
        [north, east],
      ],
      { padding: [48, 48], maxZoom: 12, animate: true },
    );
  }, [place, map]);
  return null;
}

function FitOverlay({ overlays }: { overlays: MapOverlay[] }) {
  const map = useMap();
  const lastId = useRef<string | null>(null);
  useEffect(() => {
    const last = overlays[overlays.length - 1];
    if (!last || last.id === lastId.current) return;
    // Don't auto-fit buffer-only updates
    if (last.kind === 'buffer') {
      lastId.current = last.id;
      return;
    }
    lastId.current = last.id;
    const [west, south, east, north] = last.bounds;
    map.fitBounds(
      [
        [south, west],
        [north, east],
      ],
      { padding: [40, 40], maxZoom: 15, animate: true },
    );
  }, [overlays, map]);
  return null;
}

function MapInteractionMode({ mapTool }: { mapTool: MapTool }) {
  const map = useMap();

  useEffect(() => {
    const panMode = mapTool === 'navigate';
    const container = map.getContainer();

    if (panMode) {
      map.dragging.enable();
      map.doubleClickZoom.enable();
      map.scrollWheelZoom.enable();
      map.boxZoom.enable();
      map.keyboard.enable();
      container.style.cursor = 'grab';
      container.classList.add('ev-pan-mode');
      container.classList.remove('ev-draw-mode');
    } else {
      map.dragging.disable();
      map.doubleClickZoom.disable();
      map.boxZoom.disable();
      map.scrollWheelZoom.enable();
      container.style.cursor = 'crosshair';
      container.classList.add('ev-draw-mode');
      container.classList.remove('ev-pan-mode');
    }

    return () => {
      container.style.cursor = '';
      container.classList.remove('ev-pan-mode', 'ev-draw-mode');
    };
  }, [map, mapTool]);

  useMapEvents({
    dragstart() {
      if (mapTool === 'navigate') map.getContainer().style.cursor = 'grabbing';
    },
    dragend() {
      if (mapTool === 'navigate') map.getContainer().style.cursor = 'grab';
    },
  });

  return null;
}

interface DraftState {
  points: LonLat[];
  rectStart: LonLat | null;
  cursor: LonLat | null;
}

function DrawingTools({
  mapTool,
  enablePlaceClick,
  onPlaceClick,
  onAoiComplete,
  onDrawnFeature,
  onMeasure,
  setDraft,
}: {
  mapTool: MapTool;
  enablePlaceClick: boolean;
  onPlaceClick: (lon: number, lat: number) => void;
  onAoiComplete: (feature: GeoJSON.Feature) => void;
  onDrawnFeature: (feature: DrawnFeature) => void;
  onMeasure: (label: string | null) => void;
  draft: DraftState;
  setDraft: Dispatch<SetStateAction<DraftState>>;
}) {
  const pointsRef = useRef<LonLat[]>([]);
  const rectStartRef = useRef<LonLat | null>(null);
  const suppressClick = useRef(false);
  const toolRef = useRef(mapTool);
  toolRef.current = mapTool;

  const syncDraft = (pts: LonLat[], rectStart: LonLat | null, cursor: LonLat | null = null) => {
    pointsRef.current = pts;
    rectStartRef.current = rectStart;
    setDraft({ points: pts, rectStart, cursor });
  };

  const emitLine = (pts: LonLat[], label: string) => {
    if (pts.length < 2) return;
    const geometry: GeoJSON.LineString = { type: 'LineString', coordinates: pts };
    onDrawnFeature({ type: 'LineString', geometry, label });
  };

  const finishPolygon = (pts: LonLat[], kind: 'polygon' | 'area') => {
    if (pts.length < 3) return;
    const ring = [...pts, pts[0]];
    const areaLabel = formatArea(polygonAreaSqMeters(ring));
    const geometry: GeoJSON.Polygon = { type: 'Polygon', coordinates: [ring] };
    if (kind === 'polygon') {
      onAoiComplete({
        type: 'Feature',
        properties: { kind: 'polygon', name: 'AOI' },
        geometry,
      });
      onDrawnFeature({ type: 'Polygon', geometry, label: 'AOI polygon' });
      onMeasure(`AOI area: ${areaLabel}`);
    } else {
      onDrawnFeature({ type: 'Polygon', geometry, label: 'Area polygon' });
      onMeasure(`Area: ${areaLabel}`);
    }
    syncDraft([], null, null);
  };

  useMapEvents({
    dragstart() {
      if (toolRef.current === 'navigate') suppressClick.current = true;
    },
    mousemove(e) {
      const tool = toolRef.current;
      if (tool === 'navigate' || tool === 'draw-point') return;
      const cursor: LonLat = [e.latlng.lng, e.latlng.lat];
      setDraft((prev) => ({ ...prev, cursor }));
    },
    click(e) {
      const tool = toolRef.current;
      const lon = e.latlng.lng;
      const lat = e.latlng.lat;
      const pt: LonLat = [lon, lat];

      if (tool === 'navigate') {
        if (suppressClick.current) {
          suppressClick.current = false;
          return;
        }
        if (enablePlaceClick) onPlaceClick(lon, lat);
        return;
      }

      if (tool === 'draw-point') {
        const geometry: GeoJSON.Point = { type: 'Point', coordinates: [lon, lat] };
        onDrawnFeature({ type: 'Point', geometry, label: 'Point' });
        onMeasure(`Point: ${lat.toFixed(5)}, ${lon.toFixed(5)}`);
        syncDraft([pt], null, null);
        return;
      }

      if (tool === 'measure-line') {
        const pts = [...pointsRef.current, pt];
        syncDraft(pts, null, pt);
        if (pts.length === 1) {
          onMeasure('Distance: click next point (double-click to finish)');
        } else {
          onMeasure(`Distance: ${formatDistance(pathLengthMeters(pts))} · double-click to finish`);
          emitLine(pts, 'Distance line');
        }
        return;
      }

      if (tool === 'measure-area') {
        const pts = [...pointsRef.current, pt];
        syncDraft(pts, null, pt);
        if (pts.length < 3) {
          onMeasure(`Area: ${pts.length}/3+ vertices · double-click to finish`);
        } else {
          const ring = [...pts, pts[0]];
          onMeasure(`Area: ${formatArea(polygonAreaSqMeters(ring))} · double-click to finish`);
        }
        return;
      }

      if (tool === 'aoi-poly') {
        const pts = [...pointsRef.current, pt];
        syncDraft(pts, null, pt);
        if (pts.length < 3) {
          onMeasure(`AOI: ${pts.length}/3+ vertices · double-click to finish`);
        } else {
          const ring = [...pts, pts[0]];
          onMeasure(
            `AOI: ${formatArea(polygonAreaSqMeters(ring))} · double-click to finish`,
          );
        }
        return;
      }

      if (tool === 'aoi-rect') {
        if (!rectStartRef.current) {
          syncDraft([pt], pt, pt);
          onMeasure('Rect AOI: click opposite corner');
        } else {
          const [lon0, lat0] = rectStartRef.current;
          const west = Math.min(lon0, lon);
          const east = Math.max(lon0, lon);
          const south = Math.min(lat0, lat);
          const north = Math.max(lat0, lat);
          if (east - west < 1e-8 || north - south < 1e-8) {
            onMeasure('Rect AOI: drag farther apart, click opposite corner');
            return;
          }
          const ring: LonLat[] = [
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
          ];
          const geometry: GeoJSON.Polygon = { type: 'Polygon', coordinates: [ring] };
          onAoiComplete({
            type: 'Feature',
            properties: { kind: 'rectangle', name: 'AOI' },
            geometry,
          });
          onDrawnFeature({ type: 'Polygon', geometry, label: 'AOI rectangle' });
          onMeasure(`AOI area: ${formatArea(polygonAreaSqMeters(ring))}`);
          syncDraft([], null, null);
        }
      }
    },
    dblclick(e) {
      if (e.originalEvent) {
        L.DomEvent.stop(e.originalEvent);
      }
      const tool = toolRef.current;
      suppressClick.current = false;

      if (tool === 'measure-line') {
        if (pointsRef.current.length >= 2) {
          onMeasure(`Distance: ${formatDistance(pathLengthMeters(pointsRef.current))}`);
          emitLine(pointsRef.current, 'Distance line');
        }
        syncDraft([], null, null);
        return;
      }

      if (tool === 'measure-area' || tool === 'aoi-poly') {
        const pts =
          pointsRef.current.length > 0
            ? pointsRef.current.slice(0, -1)
            : pointsRef.current;
        finishPolygon(pts, tool === 'aoi-poly' ? 'polygon' : 'area');
        return;
      }

      if (tool === 'aoi-rect') {
        syncDraft([], null, null);
        onMeasure(null);
      }
    },
  });

  useEffect(() => {
    syncDraft([], null, null);
    suppressClick.current = false;
    if (mapTool === 'draw-point') onMeasure('Point: click the map');
    else if (mapTool === 'measure-line') onMeasure('Distance: click points on the map');
    else if (mapTool === 'measure-area') onMeasure('Area: click 3+ vertices, double-click to finish');
    else if (mapTool === 'aoi-rect') onMeasure('Rect AOI: click two opposite corners');
    else if (mapTool === 'aoi-poly') onMeasure('Poly AOI: click vertices, double-click to finish');
    else onMeasure(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapTool]);

  return null;
}

function DraftGraphics({
  mapTool,
  draft,
}: {
  mapTool: MapTool;
  draft: DraftState;
}) {
  const { points, rectStart, cursor } = draft;
  const color =
    mapTool === 'measure-line' || mapTool === 'measure-area'
      ? '#0ea5e9'
      : mapTool === 'draw-point'
        ? '#0f766e'
        : '#b45309';

  const previewLine = useMemo(() => {
    if (!cursor || points.length === 0) return null;
    if (mapTool === 'measure-line' || mapTool === 'aoi-poly' || mapTool === 'measure-area') {
      return toLatLon([points[points.length - 1], cursor]);
    }
    return null;
  }, [cursor, points, mapTool]);

  const rectBounds = useMemo(() => {
    if (mapTool !== 'aoi-rect' || !rectStart || !cursor) return null;
    const [lon0, lat0] = rectStart;
    const [lon1, lat1] = cursor;
    return [
      [Math.min(lat0, lat1), Math.min(lon0, lon1)],
      [Math.max(lat0, lat1), Math.max(lon0, lon1)],
    ] as [[number, number], [number, number]];
  }, [mapTool, rectStart, cursor]);

  const closedRing = useMemo(() => {
    if (
      (mapTool === 'measure-area' || mapTool === 'aoi-poly') &&
      points.length >= 2
    ) {
      return toLatLon([...points, points[0]]);
    }
    return null;
  }, [mapTool, points]);

  return (
    <>
      {points.length >= 2 && (
        <Polyline
          positions={toLatLon(points)}
          interactive={false}
          pathOptions={{ color, weight: 2.5, opacity: 0.95 }}
        />
      )}
      {previewLine && (
        <Polyline
          positions={previewLine}
          interactive={false}
          pathOptions={{ color, weight: 2, dashArray: '6 4', opacity: 0.7 }}
        />
      )}
      {closedRing && points.length >= 3 && (
        <Polygon
          positions={closedRing}
          interactive={false}
          pathOptions={{
            color,
            weight: 2,
            fillColor: color,
            fillOpacity: 0.12,
            dashArray: '4 3',
          }}
        />
      )}
      {rectBounds && (
        <Rectangle
          bounds={rectBounds}
          interactive={false}
          pathOptions={{
            color: '#b45309',
            weight: 2,
            fillColor: '#b45309',
            fillOpacity: 0.12,
            dashArray: '6 4',
          }}
        />
      )}
      {points.map(([lon, lat], i) => (
        <CircleMarker
          key={`v-${i}`}
          center={[lat, lon]}
          radius={mapTool === 'draw-point' ? 7 : 5}
          interactive={false}
          pathOptions={{
            color: '#fff',
            weight: 2,
            fillColor: color,
            fillOpacity: 1,
          }}
        />
      ))}
    </>
  );
}

function DrawnFeatureLayer({ feature }: { feature: DrawnFeature | null }) {
  if (!feature) return null;
  if (feature.type === 'Point' && feature.geometry.type === 'Point') {
    const [lon, lat] = feature.geometry.coordinates;
    return (
      <CircleMarker
        center={[lat, lon]}
        radius={7}
        interactive={false}
        pathOptions={{ color: '#fff', weight: 2, fillColor: '#0f766e', fillOpacity: 1 }}
      />
    );
  }
  if (feature.type === 'LineString' && feature.geometry.type === 'LineString') {
    const positions = feature.geometry.coordinates.map(
      (c) => [c[1], c[0]] as LatLon,
    );
    return (
      <Polyline
        positions={positions}
        interactive={false}
        pathOptions={{ color: '#0ea5e9', weight: 3, opacity: 0.95 }}
      />
    );
  }
  if (feature.type === 'Polygon' && feature.geometry.type === 'Polygon') {
    // AOI already rendered separately; skip duplicate if same
    return null;
  }
  return null;
}

function EnsureStackPane() {
  const map = useMap();
  // DEM pane under imagery; stack pane for scenes / analysis
  if (!map.getPane('evDemPane')) {
    const dem = map.createPane('evDemPane');
    dem.style.zIndex = '440';
    dem.style.pointerEvents = 'none';
  } else {
    map.getPane('evDemPane')!.style.zIndex = '440';
  }
  if (!map.getPane('evStackPane')) {
    const pane = map.createPane('evStackPane');
    pane.style.zIndex = '450';
    pane.style.pointerEvents = 'none';
  } else {
    map.getPane('evStackPane')!.style.zIndex = '450';
  }
  return null;
}

/** Re-append stack pane children bottom→top so Layer Manager order always wins. */
function EnforceStackOrder({
  overlays,
  zIndexById,
}: {
  overlays: MapOverlay[];
  zIndexById: Map<string, number>;
}) {
  const map = useMap();

  useEffect(() => {
    const pane = map.getPane('evStackPane');
    if (!pane) return;

    const apply = () => {
      // Store order is bottom → top; appendChild moves node to end (= top)
      for (const o of overlays) {
        if (o.visible === false) continue;
        const z = String(zIndexById.get(o.id) ?? 410);
        pane.querySelectorAll(`[data-ev-id="${CSS.escape(o.id)}"]`).forEach((node) => {
          const el = node as HTMLElement;
          el.style.zIndex = z;
          pane.appendChild(el);
        });
      }
    };

    apply();
    const onAdd = () => {
      // Tag newly added leaflet layers if missing data-ev-id (fallback)
      window.requestAnimationFrame(apply);
    };
    map.on('layeradd', onAdd);
    map.on('zoomend moveend', apply);
    return () => {
      map.off('layeradd', onAdd);
      map.off('zoomend moveend', apply);
    };
  }, [map, overlays, zIndexById]);

  return null;
}

function tagOverlayElement(el: HTMLElement | undefined | null, id: string, zIndex: number) {
  if (!el) return;
  el.dataset.evId = id;
  el.style.zIndex = String(zIndex);
}

function geoStyle(kind: MapOverlay['kind']): L.PathOptions {
  if (kind === 'buffer') {
    return { color: '#7c3aed', weight: 2, fillColor: '#7c3aed', fillOpacity: 0.18 };
  }
  if (kind === 'detection') {
    return { color: '#dc2626', weight: 2.5, fillColor: '#ef4444', fillOpacity: 0.28, opacity: 0.95 };
  }
  return { color: '#0f766e', weight: 1.5, fillOpacity: 0, opacity: 0.9 };
}

function detectionPointToLayer(feature: GeoJSON.Feature, latlng: L.LatLng) {
  const conf = Number((feature.properties as { confidence?: number } | null)?.confidence ?? 0.6);
  const radius = 4 + Math.round(conf * 6);
  return L.circleMarker(latlng, {
    radius,
    color: '#991b1b',
    weight: 1.5,
    fillColor: '#ef4444',
    fillOpacity: 0.85,
    opacity: 0.95,
  });
}

export function LightMap({
  place,
  overlays,
  mapTool,
  aoiGeoJson,
  drawnFeature,
  bufferGeoJson,
  enablePlaceClick,
  showGrid = true,
  mapChrome,
  mapCommand,
  onPlaceClick,
  onAoiComplete,
  onDrawnFeature,
  onMeasure,
}: Props) {
  const [draft, setDraft] = useState<DraftState>({
    points: [],
    rectStart: null,
    cursor: null,
  });

  const chrome = {
    compass: true,
    scaleBar: true,
    coordinates: true,
    miniMap: false,
    swipe: false,
    view3d: false,
    rotate: false,
    terrainRelief: false,
    ...mapChrome,
  };

  const aoiOutline = useMemo(() => {
    if (!aoiGeoJson || aoiGeoJson.geometry.type !== 'Polygon') return null;
    return aoiGeoJson.geometry.coordinates[0].map(
      (c) => [c[1], c[0]] as LatLon,
    );
  }, [aoiGeoJson]);

  const bufferPositions = useMemo(() => {
    if (!bufferGeoJson || bufferGeoJson.type !== 'Polygon') return null;
    return bufferGeoJson.coordinates[0].map((c) => [c[1], c[0]] as LatLon);
  }, [bufferGeoJson]);

  const visibleOverlays = useMemo(
    () => overlays.filter((o) => o.visible !== false),
    [overlays],
  );

  const overlayZIndex = useMemo(() => {
    // Store order is bottom→top; map later entries higher
    const map = new Map<string, number>();
    overlays.forEach((o, i) => {
      map.set(o.id, 410 + i * 5);
    });
    return map;
  }, [overlays]);

  const demBaseOverlay = useMemo(
    () =>
      visibleOverlays.find(
        (o) => o.kind === 'terrain' && o.terrainRole === 'base' && o.demGrid?.length,
      ) ?? null,
    [visibleOverlays],
  );

  const arcSceneActive = isArcSceneMode(demBaseOverlay);

  // Fallback drape from Eye-On scene still (when API drape missing)
  const sceneTextureUrl = useMemo(() => {
    const scene = visibleOverlays.find((o) => o.kind === 'scene' && o.url);
    return scene?.url ?? null;
  }, [visibleOverlays]);

  // ArcScene mesh in stack pane (front); flat elev under imagery in dem pane
  const demZ = arcSceneActive ? 455 : 405;

  const mapStyle = useMemo(() => {
    // Mesh provides its own 3D orbit — skip CSS map warp (would misalign basemap)
    if (demBaseOverlay) return undefined;
    if (!chrome.view3d && !chrome.rotate) return undefined;
    const parts: string[] = [];
    if (chrome.view3d) parts.push('perspective(900px) rotateX(28deg)');
    if (chrome.rotate) parts.push('rotateZ(-12deg)');
    if (chrome.terrainRelief) parts.push('contrast(1.06) saturate(1.05)');
    return parts.length
      ? { transform: parts.join(' '), transformOrigin: 'center center' }
      : undefined;
  }, [chrome.view3d, chrome.rotate, chrome.terrainRelief, demBaseOverlay]);

  return (
    <div className="relative h-full w-full overflow-hidden" style={mapStyle}>
    <MapContainer
      center={[31.52, 74.35]}
      zoom={5}
      minZoom={2}
      maxZoom={18}
      zoomControl={true}
      attributionControl={false}
      className="h-full w-full"
      preferCanvas
    >
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        maxZoom={19}
        updateWhenIdle
        keepBuffer={1}
      />
      <MapInteractionMode mapTool={mapTool} />
      <MapCommandRunner command={mapCommand} />
      <EnsureStackPane />
      <EnforceStackOrder overlays={overlays} zIndexById={overlayZIndex} />
      <LatLngGrid enabled={showGrid} />
      <FlyToPlace place={place} />
      <FitOverlay overlays={visibleOverlays} />
      {/* ArcScene: draped mesh in stack pane. Flat: elev under imagery. */}
      <DemTerrainLayer
        overlay={demBaseOverlay}
        enabled={Boolean(demBaseOverlay)}
        zIndex={demZ}
        sceneTextureUrl={sceneTextureUrl}
      />
      <DrawingTools
        mapTool={mapTool}
        enablePlaceClick={enablePlaceClick}
        onPlaceClick={onPlaceClick}
        onAoiComplete={onAoiComplete}
        onDrawnFeature={onDrawnFeature}
        onMeasure={onMeasure}
        draft={draft}
        setDraft={setDraft}
      />

      {place && (
        <Marker
          position={[place.latitude, place.longitude]}
          icon={markerIcon}
          interactive={false}
        />
      )}

      {visibleOverlays.map((overlay) => {
        // DEM mesh is drawn in evDemPane; skip flat DEM raster in the imagery stack
        if (overlay.kind === 'terrain' && overlay.terrainRole === 'base') {
          return null;
        }
        const [west, south, east, north] = overlay.bounds;
        const leafletBounds: [[number, number], [number, number]] = [
          [south, west],
          [north, east],
        ];
        const footprintRing =
          overlay.kind === 'scene' &&
          overlay.footprint?.type === 'Polygon' &&
          overlay.footprint.coordinates?.[0]
            ? overlay.footprint.coordinates[0].map(
                (c) => [c[1], c[0]] as LatLon,
              )
            : null;

        const zIndex = overlayZIndex.get(overlay.id) ?? 430;
        const tagHandlers = {
          add: (e: { target: L.Layer & { getContainer?: () => HTMLElement; getElement?: () => HTMLElement } }) => {
            const el =
              e.target.getContainer?.() ||
              e.target.getElement?.() ||
              (e.target as unknown as { _container?: HTMLElement; _image?: HTMLElement })._container ||
              (e.target as unknown as { _image?: HTMLElement })._image;
            tagOverlayElement(el ?? null, overlay.id, zIndex);
          },
        };

        // ArcScene: hide flat satellite tiles — imagery is already draped on the DEM mesh.
        // Flat mode: keep translucent scenes so elev colors show under the image.
        const opacity =
          arcSceneActive && overlay.kind === 'scene'
            ? 0
            : overlay.opacity;

        return (
          <Fragment key={`${overlay.id}-z${zIndex}`}>
            {overlay.kind === 'scene' && overlay.tileUrl ? (
              <TileLayer
                url={overlay.tileUrl}
                bounds={leafletBounds}
                opacity={opacity}
                maxNativeZoom={16}
                maxZoom={18}
                pane="evStackPane"
                zIndex={zIndex}
                updateWhenZooming={false}
                updateWhenIdle
                keepBuffer={2}
                eventHandlers={tagHandlers}
              />
            ) : overlay.url ? (
              <ImageOverlay
                url={overlay.url}
                bounds={leafletBounds}
                opacity={opacity}
                interactive={false}
                pane="evStackPane"
                zIndex={zIndex}
                className={
                  overlay.kind === 'index' || overlay.kind === 'change'
                    ? 'ev-sharp-overlay'
                    : undefined
                }
                eventHandlers={tagHandlers}
              />
            ) : null}
            {overlay.geojson && (
              <GeoJSON
                key={`${overlay.id}-gj-z${zIndex}`}
                data={overlay.geojson as GeoJSON.GeoJsonObject}
                interactive={false}
                style={() => geoStyle(overlay.kind)}
                pointToLayer={
                  overlay.kind === 'detection' ? detectionPointToLayer : undefined
                }
                pane="evStackPane"
                eventHandlers={tagHandlers}
              />
            )}
            {footprintRing && (
              <Polygon
                positions={footprintRing}
                interactive={false}
                pathOptions={{
                  color: overlay.renderMode === 'grayscale' ? '#e5e7eb' : '#f59e0b',
                  weight: 2,
                  fillOpacity: 0,
                  dashArray: '6 4',
                  interactive: false,
                }}
                pane="evStackPane"
              />
            )}
          </Fragment>
        );
      })}

      <DraftGraphics mapTool={mapTool} draft={draft} />
      <DrawnFeatureLayer feature={drawnFeature} />

      {aoiOutline && (
        <Polygon
          positions={aoiOutline}
          interactive={false}
          pathOptions={{
            color: '#b45309',
            weight: 2.5,
            fillColor: '#b45309',
            fillOpacity: 0.08,
            dashArray: '6 4',
          }}
        />
      )}

      {bufferPositions && (
        <Polygon
          positions={bufferPositions}
          interactive={false}
          pathOptions={{
            color: '#7c3aed',
            weight: 2.5,
            fillColor: '#7c3aed',
            fillOpacity: 0.16,
            dashArray: '4 3',
          }}
        />
      )}

      {chrome.compass && <NorthArrow />}
      {chrome.scaleBar && <ScaleBar />}
      <CursorCoordinates enabled={Boolean(chrome.coordinates)} />
      <MiniMapPanel enabled={Boolean(chrome.miniMap)} />
      <SwipeMask enabled={Boolean(chrome.swipe)} overlays={visibleOverlays} />
    </MapContainer>
    </div>
  );
}
