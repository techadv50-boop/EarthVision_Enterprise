import { useEffect, useMemo, useRef, Fragment } from 'react';
import {
  MapContainer,
  TileLayer,
  Marker,
  Polyline,
  Polygon,
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
      // Drawing / measure tools: keep map still so clicks register cleanly
      map.dragging.disable();
      map.doubleClickZoom.disable();
      map.boxZoom.disable();
      container.style.cursor = 'crosshair';
      container.classList.add('ev-draw-mode');
      container.classList.remove('ev-pan-mode');
    }

    return () => {
      container.style.cursor = '';
      container.classList.remove('ev-pan-mode', 'ev-draw-mode');
    };
  }, [map, mapTool]);

  // Grabbing cursor while actively dragging in Pan mode
  useMapEvents({
    dragstart() {
      if (mapTool === 'navigate') {
        map.getContainer().style.cursor = 'grabbing';
      }
    },
    dragend() {
      if (mapTool === 'navigate') {
        map.getContainer().style.cursor = 'grab';
      }
    },
  });

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
  const suppressClick = useRef(false);

  useMapEvents({
    // Ignore click that follows a pan drag (Leaflet still fires click sometimes)
    dragstart() {
      if (mapTool === 'navigate') suppressClick.current = true;
    },
    click(e) {
      if (mapTool === 'navigate') {
        if (suppressClick.current) {
          suppressClick.current = false;
          return;
        }
        if (enablePlaceClick) onPlaceClick(e.latlng.lng, e.latlng.lat);
        return;
      }

      const lon = e.latlng.lng;
      const lat = e.latlng.lat;

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
      suppressClick.current = false;
    },
  });

  useEffect(() => {
    points.current = [];
    rectStart.current = null;
    suppressClick.current = false;
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
    >
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        maxZoom={19}
        updateWhenIdle
        keepBuffer={1}
      />
      <MapInteractionMode mapTool={mapTool} />
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

      {place && (
        <Marker
          position={[place.latitude, place.longitude]}
          icon={markerIcon}
          interactive={false}
        />
      )}

      {/* Scene eye → collection-specific XYZ tiles + footprint outline (tilted for Landsat/S1). */}
      {overlays.map((overlay) => {
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
                (c) => [c[1], c[0]] as [number, number],
              )
            : null;

        return (
          <Fragment key={overlay.id}>
            {overlay.kind === 'scene' && overlay.tileUrl ? (
              <TileLayer
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
            ) : overlay.url ? (
              <ImageOverlay
                url={overlay.url}
                bounds={leafletBounds}
                opacity={overlay.opacity}
                interactive={false}
                zIndex={
                  overlay.kind === 'change' ? 460 : overlay.kind === 'index' ? 450 : 430
                }
              />
            ) : null}
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
              />
            )}
          </Fragment>
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
