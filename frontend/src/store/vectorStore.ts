import { create } from 'zustand';
import * as Cesium from 'cesium';
import { useMapStore } from '@/store/mapStore';

export interface VectorLayerInfo {
  id: string;
  name: string;
  feature_count: number;
  geometry_counts: Record<string, number>;
  bbox?: number[] | null;
  original_format?: string;
  path?: string;
}

interface VectorState {
  layers: VectorLayerInfo[];
  addGeoJsonLayer: (name: string, geojson: GeoJSON.FeatureCollection, meta?: Partial<VectorLayerInfo>) => string | null;
  removeLayer: (id: string) => void;
  clearAll: () => void;
}

const VECTOR_PROP = 'sateyeUserVector';

function removeEntitiesForLayer(viewer: Cesium.Viewer, layerId: string) {
  const toRemove = viewer.entities.values.filter((entity) => {
    try {
      return entity.properties?.[VECTOR_PROP]?.getValue(Cesium.JulianDate.now()) === layerId;
    } catch {
      return false;
    }
  });
  toRemove.forEach((e) => viewer.entities.remove(e));
}

function addFeatureEntities(
  viewer: Cesium.Viewer,
  layerId: string,
  feature: GeoJSON.Feature,
  index: number,
) {
  const geom = feature.geometry;
  if (!geom) return;
  const name = String(feature.properties?.name || feature.properties?.NAME || `${layerId}_${index}`);
  const eid = `${layerId}_${index}`;

  if (geom.type === 'Point') {
    const [lon, lat] = geom.coordinates;
    viewer.entities.add({
      id: eid,
      name,
      position: Cesium.Cartesian3.fromDegrees(lon, lat),
      point: {
        pixelSize: 10,
        color: Cesium.Color.fromCssColorString('#fbbf24'),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 1,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      label: {
        text: name,
        font: '11px Space Grotesk, sans-serif',
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        pixelOffset: new Cesium.Cartesian2(0, -12),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 2.5e6),
      },
      properties: { [VECTOR_PROP]: layerId },
    });
    return;
  }

  if (geom.type === 'MultiPoint') {
    geom.coordinates.forEach((coord, i) => {
      const [lon, lat] = coord;
      viewer.entities.add({
        id: `${eid}_p${i}`,
        name,
        position: Cesium.Cartesian3.fromDegrees(lon, lat),
        point: {
          pixelSize: 8,
          color: Cesium.Color.fromCssColorString('#fbbf24'),
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 1,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        properties: { [VECTOR_PROP]: layerId },
      });
    });
    return;
  }

  if (geom.type === 'LineString') {
    const positions = geom.coordinates.flatMap(([lon, lat]) => [lon, lat]);
    viewer.entities.add({
      id: eid,
      name,
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray(positions),
        width: 2.5,
        material: Cesium.Color.fromCssColorString('#38bdf8'),
        clampToGround: true,
      },
      properties: { [VECTOR_PROP]: layerId },
    });
    return;
  }

  if (geom.type === 'MultiLineString') {
    geom.coordinates.forEach((line, i) => {
      const positions = line.flatMap(([lon, lat]) => [lon, lat]);
      viewer.entities.add({
        id: `${eid}_l${i}`,
        name,
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArray(positions),
          width: 2.5,
          material: Cesium.Color.fromCssColorString('#38bdf8'),
          clampToGround: true,
        },
        properties: { [VECTOR_PROP]: layerId },
      });
    });
    return;
  }

  if (geom.type === 'Polygon') {
    const ring = geom.coordinates[0] as number[][];
    const hierarchy = ring.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat));
    viewer.entities.add({
      id: eid,
      name,
      polygon: {
        hierarchy,
        material: Cesium.Color.fromCssColorString('#2dd4bf').withAlpha(0.28),
        outline: true,
        outlineColor: Cesium.Color.fromCssColorString('#5eead4'),
        height: 0,
      },
      properties: { [VECTOR_PROP]: layerId },
    });
    return;
  }

  if (geom.type === 'MultiPolygon') {
    geom.coordinates.forEach((poly, i) => {
      const ring = poly[0] as number[][];
      const hierarchy = ring.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat));
      viewer.entities.add({
        id: `${eid}_g${i}`,
        name,
        polygon: {
          hierarchy,
          material: Cesium.Color.fromCssColorString('#2dd4bf').withAlpha(0.28),
          outline: true,
          outlineColor: Cesium.Color.fromCssColorString('#5eead4'),
          height: 0,
        },
        properties: { [VECTOR_PROP]: layerId },
      });
    });
  }
}

export const useVectorStore = create<VectorState>((set, get) => ({
  layers: [],

  addGeoJsonLayer: (name, geojson, meta) => {
    const viewer = useMapStore.getState().viewer;
    if (!viewer) return null;
    const id = `vec_${Date.now().toString(36)}`;
    const features = geojson.features || [];
    features.forEach((f, i) => addFeatureEntities(viewer, id, f, i));

    // Fly to bbox if available
    const bbox = meta?.bbox;
    if (bbox && bbox.length >= 4) {
      const [west, south, east, north] = bbox;
      void viewer.camera.flyTo({
        destination: Cesium.Rectangle.fromDegrees(west, south, east, north),
        duration: 1.5,
      });
    }

    const info: VectorLayerInfo = {
      id,
      name,
      feature_count: meta?.feature_count ?? features.length,
      geometry_counts: meta?.geometry_counts ?? {},
      bbox: meta?.bbox,
      original_format: meta?.original_format,
      path: meta?.path,
    };
    set({ layers: [info, ...get().layers] });
    return id;
  },

  removeLayer: (id) => {
    const viewer = useMapStore.getState().viewer;
    if (viewer) removeEntitiesForLayer(viewer, id);
    set({ layers: get().layers.filter((l) => l.id !== id) });
  },

  clearAll: () => {
    const viewer = useMapStore.getState().viewer;
    for (const layer of get().layers) {
      if (viewer) removeEntitiesForLayer(viewer, layer.id);
    }
    set({ layers: [] });
  },
}));
