import { useEffect, useMemo, useRef } from 'react';
import {
  MapContainer,
  TileLayer,
  Marker,
  Polyline,
  ImageOverlay,
  useMap,
  useMapEvents,
} from 'react-leaflet';
import L from 'leaflet';
import type { PlaceSelection, MapTool, MapOverlay } from '../store/workflowStore';
import {
  formatArea,
  formatDistance,
  pathLengthMeters,
  polygonAreaSqMeters,
} from '../utils/geoMath';
import { LatLngGrid, NorthArrow, ScaleBar } from '../components/map/MapDecorations';
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
  overlays: MapOverlay[];
  mapTool: MapTool;
  aoiGeoJson: GeoJSON.Feature | null;
  enablePlaceClick: boolean;
  showGrid?: boolean;
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
      { padding: [40, 40], maxZoom: 15, animate: true },
    );
  }, [overlays, map]);
  return null;
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
  const points = useRef<Array<[number, number]>>([]);
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
          onMeasure(`Distance: ${formatDistance(pathLengthMeters(points.current))}`);
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
      points.current = [];
    },
  });

  useEffect(() => {
    points.current = [];
    rectStart.current = null;
  }, [mapTool]);

  return null;
}

export function LightMap({
  place,
  overlays,
  mapTool,
  aoiGeoJson,
  enablePlaceClick,
  showGrid = true,
  onPlaceClick,
  onAoiComplete,
  onMeasure,
}: Props) {
  const aoiOutline = useMemo(() => {
    if (!aoiGeoJson || aoiGeoJson.geometry.type !== 'Polygon') return null;
    // Only show outline while an AOI draw tool is active — never filled boxes
    if (mapTool === 'navigate') return null;
    return aoiGeoJson.geometry.coordinates[0].map(
      (c) => [c[1], c[0]] as [number, number],
    );
  }, [aoiGeoJson, mapTool]);

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
      <LatLngGrid enabled={showGrid} />
      <FlyToPlace place={place} />
      <FitOverlay overlays={overlays} />
      <DrawingHandler
        mapTool={mapTool}
        enablePlaceClick={enablePlaceClick}
        onPlaceClick={onPlaceClick}
        onAoiComplete={onAoiComplete}
        onMeasure={onMeasure}
      />

      {place && <Marker position={[place.latitude, place.longitude]} icon={markerIcon} />}

      {/* Scene eye → Sentinel-2 TCI XYZ tiles (sharp on zoom). Indices/change stay ImageOverlay. */}
      {overlays.map((overlay) => {
        const [west, south, east, north] = overlay.bounds;
        const leafletBounds: [[number, number], [number, number]] = [
          [south, west],
          [north, east],
        ];
        if (overlay.kind === 'scene' && overlay.tileUrl) {
          return (
            <TileLayer
              key={overlay.id}
              url={overlay.tileUrl}
              bounds={leafletBounds}
              opacity={overlay.opacity}
              maxNativeZoom={16}
              maxZoom={18}
              zIndex={430}
              updateWhenZooming={false}
              updateWhenIdle
              keepBuffer={2}
            />
          );
        }
        if (!overlay.url) return null;
        return (
          <ImageOverlay
            key={overlay.id}
            url={overlay.url}
            bounds={leafletBounds}
            opacity={overlay.opacity}
            zIndex={
              overlay.kind === 'change' ? 460 : overlay.kind === 'index' ? 450 : 430
            }
          />
        );
      })}

      {aoiOutline && (
        <Polyline
          positions={aoiOutline}
          pathOptions={{ color: '#b45309', weight: 2, dashArray: '4 4' }}
        />
      )}

      <NorthArrow />
      <ScaleBar />
    </MapContainer>
  );
}
