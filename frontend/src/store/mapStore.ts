import { create } from 'zustand';
import * as Cesium from 'cesium';
import type { Feature } from 'geojson';

export interface MousePosition {
  longitude: number;
  latitude: number;
  altitude: number;
}

export interface Bookmark {
  id: number;
  name: string;
  description?: string;
  longitude: number;
  latitude: number;
  altitude: number;
  heading: number;
  pitch: number;
  roll: number;
}

export interface AOI {
  id: number;
  name: string;
  geometry_type: string;
  geojson: string;
}

export interface SceneResult {
  scene_id: string;
  collection: string;
  platform: string;
  acquisition_date: string;
  cloud_cover?: number;
  footprint_geojson?: string;
  preview_url?: string;
  metadata?: Record<string, unknown>;
}

interface MapState {
  viewer: Cesium.Viewer | null;
  setViewer: (viewer: Cesium.Viewer | null) => void;
  mousePosition: MousePosition;
  setMousePosition: (pos: MousePosition) => void;
  cameraHeight: number;
  setCameraHeight: (height: number) => void;
  heading: number;
  setHeading: (heading: number) => void;
  bookmarks: Bookmark[];
  setBookmarks: (bookmarks: Bookmark[]) => void;
  aois: AOI[];
  setAois: (aois: AOI[]) => void;
  activeTool: 'navigate' | 'polygon' | 'rectangle' | 'circle' | 'measure' | 'marker';
  setActiveTool: (tool: MapState['activeTool']) => void;
  drawnGeometries: Feature[];
  addGeometry: (feature: Feature) => void;
  clearGeometries: () => void;
  searchResults: Array<{ name: string; display_name: string; longitude: number; latitude: number }>;
  setSearchResults: (results: MapState['searchResults']) => void;
  scenes: SceneResult[];
  setScenes: (scenes: SceneResult[]) => void;
  selectedScene: SceneResult | null;
  setSelectedScene: (scene: SceneResult | null) => void;
  layerVisibility: Record<string, boolean>;
  toggleLayer: (layerId: string) => void;
  flyTo: (
    longitude: number,
    latitude: number,
    altitude?: number,
    orientation?: { heading?: number; pitch?: number; roll?: number },
  ) => void;
  renderSearchMarkers: (
    results: Array<{ name: string; display_name: string; longitude: number; latitude: number }>,
  ) => void;
  clearSearchMarkers: () => void;
  renderFootprints: (scenes: SceneResult[]) => void;
  clearFootprints: () => void;
  renderAois: (aois: AOI[]) => void;
  addSceneImageryLayer: (sceneId: string) => void;
  removeSceneImageryLayer: (sceneId: string) => void;
  addAnalysisLayer: (urlTemplate: string) => void;
  removeAnalysisLayer: () => void;
  analysisLayer: Cesium.ImageryLayer | null;
  sceneLayers: Record<string, Cesium.ImageryLayer>;
}

const FOOTPRINT_PROP = 'earthvisionFootprint';
const AOI_PROP = 'earthvisionAoi';
const DRAWN_PROP = 'earthvisionDrawn';
const SEARCH_PROP = 'earthvisionSearch';

function tileAuthQuery(): string {
  const token = localStorage.getItem('access_token');
  return token ? `token=${encodeURIComponent(token)}` : '';
}

function removeEntitiesByProperty(viewer: Cesium.Viewer, property: string) {
  const toRemove = viewer.entities.values.filter((entity) => {
    try {
      return entity.properties?.[property]?.getValue(Cesium.JulianDate.now()) === true;
    } catch {
      return false;
    }
  });
  toRemove.forEach((entity) => viewer.entities.remove(entity));
}

function parsePolygonCoords(geojsonStr: string): number[][] | null {
  try {
    const geo = JSON.parse(geojsonStr);
    if (geo.type === 'Feature') {
      if (geo.geometry?.type === 'Polygon') return geo.geometry.coordinates[0];
    }
    if (geo.type === 'Polygon') return geo.coordinates[0];
    if (geo.type === 'FeatureCollection' && geo.features?.[0]) {
      const g = geo.features[0].geometry;
      if (g?.type === 'Polygon') return g.coordinates[0];
    }
  } catch {
    return null;
  }
  return null;
}

export const useMapStore = create<MapState>((set, get) => ({
  viewer: null,
  setViewer: (viewer) => set({ viewer }),
  mousePosition: { longitude: 0, latitude: 0, altitude: 0 },
  setMousePosition: (pos) => set({ mousePosition: pos }),
  cameraHeight: 15000000,
  setCameraHeight: (height) => set({ cameraHeight: height }),
  heading: 0,
  setHeading: (heading) => set({ heading }),
  bookmarks: [],
  setBookmarks: (bookmarks) => set({ bookmarks }),
  aois: [],
  setAois: (aois) => set({ aois }),
  activeTool: 'navigate',
  setActiveTool: (tool) => set({ activeTool: tool }),
  drawnGeometries: [],
  addGeometry: (feature) =>
    set((state) => ({ drawnGeometries: [...state.drawnGeometries, feature] })),
  clearGeometries: () => {
    const { viewer } = get();
    if (viewer) removeEntitiesByProperty(viewer, DRAWN_PROP);
    set({ drawnGeometries: [] });
  },
  searchResults: [],
  setSearchResults: (results) => set({ searchResults: results }),
  scenes: [],
  setScenes: (scenes) => set({ scenes }),
  selectedScene: null,
  setSelectedScene: (scene) => set({ selectedScene: scene }),
  layerVisibility: {
    terrain: true,
    imagery: true,
    footprints: true,
    aoi: true,
  },
  analysisLayer: null,
  sceneLayers: {},
  toggleLayer: (layerId) => {
    const { viewer, layerVisibility } = get();
    const next = !layerVisibility[layerId];
    set({
      layerVisibility: { ...layerVisibility, [layerId]: next },
    });
    if (!viewer) return;

    if (layerId === 'terrain') {
      // Offline PC mode: ellipsoid only (no Cesium Ion world terrain)
      viewer.scene.globe.depthTestAgainstTerrain = next;
      viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
    }

    if (layerId === 'imagery') {
      const layers = viewer.imageryLayers;
      for (let i = 0; i < layers.length; i++) {
        const layer = layers.get(i);
        if (layer !== get().analysisLayer) {
          layer.show = next;
        }
      }
    }

    if (layerId === 'footprints') {
      viewer.entities.values.forEach((entity) => {
        try {
          if (entity.properties?.[FOOTPRINT_PROP]?.getValue(Cesium.JulianDate.now()) === true) {
            entity.show = next;
          }
        } catch {
          /* ignore */
        }
      });
    }

    if (layerId === 'aoi') {
      viewer.entities.values.forEach((entity) => {
        try {
          if (entity.properties?.[AOI_PROP]?.getValue(Cesium.JulianDate.now()) === true) {
            entity.show = next;
          }
        } catch {
          /* ignore */
        }
      });
    }
  },
  flyTo: (longitude, latitude, altitude = 10000, orientation) => {
    const { viewer } = get();
    if (!viewer) return;
    const options: Parameters<Cesium.Camera['flyTo']>[0] = {
      destination: Cesium.Cartesian3.fromDegrees(longitude, latitude, altitude),
      duration: 2.0,
    };
    if (orientation) {
      options.orientation = {
        heading: Cesium.Math.toRadians(orientation.heading ?? 0),
        pitch: Cesium.Math.toRadians(orientation.pitch ?? -45),
        roll: Cesium.Math.toRadians(orientation.roll ?? 0),
      };
    }
    viewer.camera.flyTo(options);
  },
  renderSearchMarkers: (results) => {
    const { viewer } = get();
    if (!viewer) return;
    removeEntitiesByProperty(viewer, SEARCH_PROP);
    for (const result of results) {
      viewer.entities.add({
        name: result.name,
        position: Cesium.Cartesian3.fromDegrees(result.longitude, result.latitude),
        point: {
          pixelSize: 12,
          color: Cesium.Color.fromCssColorString('#38bdf8'),
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: 2,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        label: {
          text: result.name,
          font: '12px sans-serif',
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          pixelOffset: new Cesium.Cartesian2(0, -16),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        properties: { [SEARCH_PROP]: true },
      });
    }
  },
  clearSearchMarkers: () => {
    const { viewer } = get();
    if (viewer) removeEntitiesByProperty(viewer, SEARCH_PROP);
  },
  renderFootprints: (scenes) => {
    const { viewer, layerVisibility } = get();
    if (!viewer) return;
    removeEntitiesByProperty(viewer, FOOTPRINT_PROP);

    for (const scene of scenes) {
      if (!scene.footprint_geojson) continue;
      const coords = parsePolygonCoords(scene.footprint_geojson);
      if (!coords || coords.length < 3) continue;

      const hierarchy = coords.map(([lon, lat]) =>
        Cesium.Cartesian3.fromDegrees(lon, lat)
      );

      viewer.entities.add({
        name: scene.scene_id,
        polygon: {
          hierarchy,
          material: Cesium.Color.CYAN.withAlpha(0.25),
          outline: true,
          outlineColor: Cesium.Color.CYAN,
          outlineWidth: 2,
          height: 0,
        },
        properties: {
          [FOOTPRINT_PROP]: true,
          sceneId: scene.scene_id,
        },
        show: layerVisibility.footprints,
      });
    }
  },
  clearFootprints: () => {
    const { viewer } = get();
    if (viewer) removeEntitiesByProperty(viewer, FOOTPRINT_PROP);
  },
  renderAois: (aois) => {
    const { viewer, layerVisibility } = get();
    if (!viewer) return;
    removeEntitiesByProperty(viewer, AOI_PROP);

    for (const aoi of aois) {
      const coords = parsePolygonCoords(aoi.geojson);
      if (!coords || coords.length < 3) continue;

      const hierarchy = coords.map(([lon, lat]) =>
        Cesium.Cartesian3.fromDegrees(lon, lat)
      );

      viewer.entities.add({
        name: aoi.name,
        polygon: {
          hierarchy,
          material: Cesium.Color.LIME.withAlpha(0.2),
          outline: true,
          outlineColor: Cesium.Color.LIME,
          height: 0,
        },
        properties: {
          [AOI_PROP]: true,
          aoiId: aoi.id,
        },
        show: layerVisibility.aoi,
      });
    }
  },
  addSceneImageryLayer: (sceneId) => {
    const { viewer, sceneLayers } = get();
    if (!viewer) return;
    if (sceneLayers[sceneId]) {
      viewer.imageryLayers.remove(sceneLayers[sceneId], true);
    }
    const auth = tileAuthQuery();
    const url = `/api/v1/raster/tiles/scene/${encodeURIComponent(sceneId)}/{z}/{x}/{y}.png${auth ? `?${auth}` : ''}`;
    const provider = new Cesium.UrlTemplateImageryProvider({
      url,
      tilingScheme: new Cesium.WebMercatorTilingScheme(),
      maximumLevel: 18,
    });
    const layer = viewer.imageryLayers.addImageryProvider(provider);
    layer.alpha = 0.9;
    set({ sceneLayers: { ...get().sceneLayers, [sceneId]: layer } });
  },
  removeSceneImageryLayer: (sceneId) => {
    const { viewer, sceneLayers } = get();
    const layer = sceneLayers[sceneId];
    if (viewer && layer) {
      viewer.imageryLayers.remove(layer, true);
    }
    const next = { ...sceneLayers };
    delete next[sceneId];
    set({ sceneLayers: next });
  },
  addAnalysisLayer: (urlTemplate) => {
    const { viewer, analysisLayer } = get();
    if (!viewer) return;
    if (analysisLayer) {
      viewer.imageryLayers.remove(analysisLayer, true);
    }
    const auth = tileAuthQuery();
    const separator = urlTemplate.includes('?') ? '&' : '?';
    const url = auth ? `${urlTemplate}${separator}${auth}` : urlTemplate;
    const provider = new Cesium.UrlTemplateImageryProvider({
      url,
      tilingScheme: new Cesium.WebMercatorTilingScheme(),
      maximumLevel: 18,
    });
    const layer = viewer.imageryLayers.addImageryProvider(provider);
    layer.alpha = 0.75;
    set({ analysisLayer: layer });
  },
  removeAnalysisLayer: () => {
    const { viewer, analysisLayer } = get();
    if (viewer && analysisLayer) {
      viewer.imageryLayers.remove(analysisLayer, true);
    }
    set({ analysisLayer: null });
  },
}));

export { DRAWN_PROP };
