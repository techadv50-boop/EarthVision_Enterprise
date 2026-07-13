import { useEffect, useMemo, useRef } from 'react';
import {
  MapContainer,
  TileLayer,
  Marker,
  Polygon,
  Polyline,
  ImageOverlay,
  useMap,
  useMapEvents,
} from 'react-leaflet';
import L from 'leaflet';
import type { PlaceSelection, MapTool, MapOverlay } from '../store/workflowStore';
import type { SceneSummary } from '../services/catalogService';
import {
  formatArea,
  formatDistance,
  pathLengthMeters,
  polygonAreaSqMeters,
} from '../utils/geoMath';
import 'leaflet/dist/leaflet.css';

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
  scenes: SceneSummary[];
  selectedScene: SceneSummary | null;
  overlays: MapOverlay[];
  mapTool: MapTool;
  aoiGeoJson: GeoJSON.Feature | null;
  enablePlaceClick: boolean;
  onPlaceClick: (lon: number, lat: number) => void;
  onAoiComplete: (feature: GeoJSON.Feature) => void;
  onMeasure: (label: string) => void;
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
    lastId.current = last.id;
    const [west, south, east, north] = last.bounds;
    map.fitBounds(
      [
        [south, west],
        [north, east],
      ],
      { padding: [40, 40], maxZoom: 13, animate: true },
    );
  }, [overlays, map]);
  return null;
}

function footprintPositions(scene: SceneSummary): [number, number][] | null {
  const fp = scene.footprint as GeoJSON.Polygon | undefined;
  if (!fp || fp.type !== 'Polygon' || !fp.coordinates?.[0]?.length) return null;
  return fp.coordinates[0].map((c) => [c[1], c[0]] as [number, number]);
}

function DrawingHandler({
  mapTool,
  enablePlaceClick,
  onPlaceClick,
  onAoiComplete,
  onMeasure,
}: {
  mapTool: MapTool;
  enablePlaceClick: boolean;
  onPlaceClick: (lon: number, lat: number) => void;
  onAoiComplete: (feature: GeoJSON.Feature) => void;
  onMeasure: (label: string) => void;
}) {
  const points = useRef<Array<[number, number]>>([]); // lon,lat
  const rectStart = useRef<[number, number] | null>(null);

  useMapEvents({
    click(e) {
      const lon = e.latlng.lng;
      const lat = e.latlng.lat;

      if (mapTool === 'navigate') {
        if (enablePlaceClick) onPlaceClick(lon, lat);
        return;
      }

      if (mapTool === 'measure-line') {
        points.current.push([lon, lat]);
        if (points.current.length >= 2) {
          const meters = pathLengthMeters(points.current);
          onMeasure(`Distance: ${formatDistance(meters)}`);
        }
        return;
      }

      if (mapTool === 'measure-area') {
        points.current.push([lon, lat]);
        if (points.current.length >= 3) {
          const ring = [...points.current, points.current[0]];
          onMeasure(`Area: ${formatArea(polygonAreaSqMeters(ring))}`);
        }
        return;
      }

      if (mapTool === 'aoi-poly') {
        points.current.push([lon, lat]);
        if (points.current.length >= 3) {
          const ring = [...points.current, points.current[0]];
          onAoiComplete({
            type: 'Feature',
            properties: { kind: 'polygon', name: 'AOI' },
            geometry: { type: 'Polygon', coordinates: [ring] },
          });
          onMeasure(`AOI area: ${formatArea(polygonAreaSqMeters(ring))}`);
        }
        return;
      }

      if (mapTool === 'aoi-rect') {
        if (!rectStart.current) {
          rectStart.current = [lon, lat];
          onMeasure('Click opposite corner to finish rectangle');
        } else {
          const [lon0, lat0] = rectStart.current;
          const west = Math.min(lon0, lon);
          const east = Math.max(lon0, lon);
          const south = Math.min(lat0, lat);
          const north = Math.max(lat0, lat);
          const ring: Array<[number, number]> = [
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
          ];
          onAoiComplete({
            type: 'Feature',
            properties: { kind: 'rectangle', name: 'AOI' },
            geometry: { type: 'Polygon', coordinates: [ring] },
          });
          onMeasure(`AOI area: ${formatArea(polygonAreaSqMeters(ring))}`);
          rectStart.current = null;
          points.current = [];
        }
      }
    },
    dblclick() {
      if (mapTool === 'measure-line' || mapTool === 'measure-area' || mapTool === 'aoi-poly') {
        if (mapTool === 'aoi-poly' && points.current.length >= 3) {
          const ring = [...points.current, points.current[0]];
          onAoiComplete({
            type: 'Feature',
            properties: { kind: 'polygon', name: 'AOI' },
            geometry: { type: 'Polygon', coordinates: [ring] },
          });
        }
        points.current = [];
      }
    },
  });

  useEffect(() => {
    points.current = [];
    rectStart.current = null;
  }, [mapTool]);

  return null;
}

function SketchLayer({ mapTool }: { mapTool: MapTool }) {
  // Visual feedback handled via AOI prop; keep hook for future live sketch
  void mapTool;
  return null;
}

export function LightMap({
  place,
  scenes,
  selectedScene,
  overlays,
  mapTool,
  aoiGeoJson,
  enablePlaceClick,
  onPlaceClick,
  onAoiComplete,
  onMeasure,
}: Props) {
  const footprints = useMemo(() => {
    return scenes
      .map((scene) => {
        const positions = footprintPositions(scene);
        if (!positions) return null;
        return { scene, positions };
      })
      .filter(Boolean) as Array<{ scene: SceneSummary; positions: [number, number][] }>;
  }, [scenes]);

  const aoiPositions = useMemo(() => {
    if (!aoiGeoJson || aoiGeoJson.geometry.type !== 'Polygon') return null;
    return aoiGeoJson.geometry.coordinates[0].map(
      (c) => [c[1], c[0]] as [number, number],
    );
  }, [aoiGeoJson]);

  return (
    <MapContainer
      center={[31.52, 74.35]}
      zoom={5}
      minZoom={2}
      maxZoom={18}
      zoomControl={true}
      attributionControl={false}
      className="h-full w-full"
      preferCanvas
      doubleClickZoom={mapTool === 'navigate'}
    >
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        maxZoom={19}
        updateWhenIdle
        keepBuffer={1}
      />
      <FlyToPlace place={place} />
      <FitOverlay overlays={overlays} />
      <DrawingHandler
        mapTool={mapTool}
        enablePlaceClick={enablePlaceClick}
        onPlaceClick={onPlaceClick}
        onAoiComplete={onAoiComplete}
        onMeasure={onMeasure}
      />
      <SketchLayer mapTool={mapTool} />

      {place && <Marker position={[place.latitude, place.longitude]} icon={markerIcon} />}

      {footprints.map(({ scene, positions }) => {
        const active = selectedScene?.id === scene.id;
        return (
          <Polygon
            key={scene.id}
            positions={positions}
            pathOptions={{
              color: active ? '#0d9488' : '#64748b',
              weight: active ? 2 : 1,
              fillColor: active ? '#14b8a6' : '#94a3b8',
              fillOpacity: overlays.length ? 0.05 : active ? 0.2 : 0.08,
            }}
          />
        );
      })}

      {overlays.map((overlay) => {
        const [west, south, east, north] = overlay.bounds;
        return (
          <ImageOverlay
            key={overlay.id}
            url={overlay.url}
            bounds={[
              [south, west],
              [north, east],
            ]}
            opacity={overlay.opacity}
            zIndex={overlay.kind === 'change' ? 450 : overlay.kind === 'index' ? 440 : 430}
          />
        );
      })}

      {aoiPositions && (
        <Polygon
          positions={aoiPositions}
          pathOptions={{
            color: '#b45309',
            weight: 2,
            fillColor: '#f59e0b',
            fillOpacity: 0.15,
            dashArray: '6 4',
          }}
        />
      )}

      {aoiPositions && aoiPositions.length > 1 && (
        <Polyline
          positions={aoiPositions}
          pathOptions={{ color: '#b45309', weight: 2, dashArray: '4 4' }}
        />
      )}
    </MapContainer>
  );
}
