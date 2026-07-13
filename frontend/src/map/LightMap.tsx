import { useEffect, useMemo } from 'react';
import {
  MapContainer,
  TileLayer,
  Marker,
  CircleMarker,
  Polygon,
  useMap,
  useMapEvents,
} from 'react-leaflet';
import L from 'leaflet';
import type { PlaceSelection } from '../store/workflowStore';
import type { SceneSummary } from '../services/catalogService';
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
  onMapClick: (lon: number, lat: number) => void;
}

function MapClickHandler({ onMapClick }: { onMapClick: (lon: number, lat: number) => void }) {
  useMapEvents({
    click(e) {
      onMapClick(e.latlng.lng, e.latlng.lat);
    },
  });
  return null;
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
      { padding: [40, 40], maxZoom: 11, animate: true },
    );
  }, [place, map]);
  return null;
}

function footprintPositions(scene: SceneSummary): [number, number][] | null {
  const fp = scene.footprint as GeoJSON.Polygon | undefined;
  if (!fp || fp.type !== 'Polygon' || !fp.coordinates?.[0]?.length) return null;
  return fp.coordinates[0].map((c) => [c[1], c[0]] as [number, number]);
}

export function LightMap({ place, scenes, selectedScene, onMapClick }: Props) {
  const footprints = useMemo(() => {
    return scenes
      .map((scene) => {
        const positions = footprintPositions(scene);
        if (!positions) return null;
        return { scene, positions };
      })
      .filter(Boolean) as Array<{ scene: SceneSummary; positions: [number, number][] }>;
  }, [scenes]);

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
      <MapClickHandler onMapClick={onMapClick} />
      <FlyToPlace place={place} />

      {place && <Marker position={[place.latitude, place.longitude]} icon={markerIcon} />}

      {footprints.map(({ scene, positions }) => {
        const active = selectedScene?.id === scene.id;
        return (
          <Polygon
            key={scene.id}
            positions={positions}
            pathOptions={{
              color: active ? '#0d9488' : '#1f6f54',
              weight: active ? 2.5 : 1,
              fillColor: active ? '#14b8a6' : '#1f6f54',
              fillOpacity: active ? 0.28 : 0.12,
            }}
          />
        );
      })}

      {!place && (
        <CircleMarker
          center={[31.52, 74.35]}
          radius={4}
          pathOptions={{ color: '#1f6f54', fillOpacity: 0.4 }}
        />
      )}
    </MapContainer>
  );
}
