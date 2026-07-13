import {
  Cartesian2,
  Cartesian3,
  Cartographic,
  Color,
  ColorMaterialProperty,
  ConstantProperty,
  createWorldTerrainAsync,
  CustomDataSource,
  Entity,
  HeightReference,
  ImageryLayer,
  Ion,
  Math as CesiumMath,
  OpenStreetMapImageryProvider,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  Viewer,
  UrlTemplateImageryProvider,
  defined,
  sampleTerrainMostDetailed,
} from 'cesium';
import type { SceneSummary } from '../services/catalogService';

const ION_TOKEN = import.meta.env.VITE_CESIUM_ION_TOKEN || '';

if (ION_TOKEN) {
  Ion.defaultAccessToken = ION_TOKEN;
}

export interface ViewerHandles {
  viewer: Viewer;
  footprints: CustomDataSource;
  aoi: CustomDataSource;
  markers: CustomDataSource;
  destroy: () => void;
}

export async function createEarthVisionViewer(
  container: HTMLElement,
): Promise<ViewerHandles> {
  const viewer = new Viewer(container, {
    animation: false,
    timeline: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
    creditContainer: document.createElement('div'),
    terrainProvider: undefined,
  });

  viewer.scene.globe.enableLighting = true;
  viewer.scene.globe.depthTestAgainstTerrain = true;
  viewer.scene.fog.enabled = true;
  if (viewer.scene.skyAtmosphere) {
    viewer.scene.skyAtmosphere.show = true;
  }
  viewer.scene.globe.showGroundAtmosphere = true;
  viewer.scene.screenSpaceCameraController.minimumZoomDistance = 100;
  viewer.scene.screenSpaceCameraController.maximumZoomDistance = 40_000_000;

  try {
    const terrain = await createWorldTerrainAsync();
    viewer.terrainProvider = terrain;
  } catch {
    // Terrain optional when Ion token missing
  }

  // Default imagery — OpenStreetMap as reliable basemap
  viewer.imageryLayers.removeAll();
  viewer.imageryLayers.addImageryProvider(
    new OpenStreetMapImageryProvider({
      url: 'https://tile.openstreetmap.org/',
    }),
  );

  const footprints = new CustomDataSource('footprints');
  const aoi = new CustomDataSource('aoi');
  const markers = new CustomDataSource('markers');
  await viewer.dataSources.add(footprints);
  await viewer.dataSources.add(aoi);
  await viewer.dataSources.add(markers);

  viewer.camera.flyTo({
    destination: Cartesian3.fromDegrees(10, 20, 18_000_000),
    duration: 0,
  });

  const destroy = () => {
    if (!viewer.isDestroyed()) {
      viewer.destroy();
    }
  };

  return { viewer, footprints, aoi, markers, destroy };
}

export function flyTo(
  viewer: Viewer,
  lon: number,
  lat: number,
  height = 500_000,
  duration = 2.2,
): void {
  viewer.camera.flyTo({
    destination: Cartesian3.fromDegrees(lon, lat, height),
    duration,
    orientation: {
      heading: 0,
      pitch: CesiumMath.toRadians(-45),
      roll: 0,
    },
  });
}

export function addMarkerEntity(
  source: CustomDataSource,
  lon: number,
  lat: number,
  label: string,
): Entity {
  return source.entities.add({
    position: Cartesian3.fromDegrees(lon, lat),
    point: {
      pixelSize: 12,
      color: Color.fromCssColorString('#3ba3c7'),
      outlineColor: Color.WHITE,
      outlineWidth: 2,
      heightReference: HeightReference.CLAMP_TO_GROUND,
    },
    label: {
      text: label,
      font: '14px IBM Plex Sans',
      fillColor: Color.WHITE,
      outlineColor: Color.fromCssColorString('#0b211a'),
      outlineWidth: 3,
      style: 2,
      verticalOrigin: 1,
      pixelOffset: new Cartesian2(0, -18),
      heightReference: HeightReference.CLAMP_TO_GROUND,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
  });
}

export function renderSceneFootprints(
  source: CustomDataSource,
  scenes: SceneSummary[],
  onSelect?: (scene: SceneSummary) => void,
): void {
  source.entities.removeAll();
  for (const scene of scenes) {
    const fp = scene.footprint as GeoJSON.Polygon | undefined;
    if (!fp || fp.type !== 'Polygon') continue;
    const ring = fp.coordinates[0];
    if (!ring?.length) continue;
    const positions = ring.map((coord: number[]) => Cartesian3.fromDegrees(coord[0], coord[1]));
    const entity = source.entities.add({
      id: `scene-${scene.id}`,
      name: scene.name,
      polygon: {
        hierarchy: positions,
        material: new ColorMaterialProperty(
          Color.fromCssColorString('#3ba3c7').withAlpha(0.22),
        ),
        outline: true,
        outlineColor: Color.fromCssColorString('#7ec8e3'),
        outlineWidth: 2,
        heightReference: HeightReference.CLAMP_TO_GROUND,
      },
      properties: {
        sceneId: scene.id,
      },
    });
    entity.description = new ConstantProperty(
      `${scene.collection} · cloud ${scene.cloud_cover ?? 'n/a'}%`,
    );
    void onSelect;
  }
}

export function setAoiEntity(
  source: CustomDataSource,
  feature: GeoJSON.Feature | null,
): void {
  source.entities.removeAll();
  if (!feature?.geometry) return;
  const geom = feature.geometry;
  if (geom.type === 'Polygon') {
    const ring = geom.coordinates[0];
    const positions = ring.map((coord: number[]) => Cartesian3.fromDegrees(coord[0], coord[1]));
    source.entities.add({
      polygon: {
        hierarchy: positions,
        material: Color.fromCssColorString('#c4a574').withAlpha(0.28),
        outline: true,
        outlineColor: Color.fromCssColorString('#c4a574'),
        outlineWidth: 2,
        heightReference: HeightReference.CLAMP_TO_GROUND,
      },
      polyline: {
        positions,
        width: 3,
        material: Color.fromCssColorString('#c4a574'),
        clampToGround: true,
      },
    });
  }
}

export function pickCoords(
  viewer: Viewer,
  position: Cartesian2,
): { longitude: number; latitude: number; height: number } | null {
  const cartesian = viewer.camera.pickEllipsoid(position, viewer.scene.globe.ellipsoid);
  if (!defined(cartesian) || !cartesian) return null;
  const carto = Cartographic.fromCartesian(cartesian);
  return {
    longitude: CesiumMath.toDegrees(carto.longitude),
    latitude: CesiumMath.toDegrees(carto.latitude),
    height: carto.height,
  };
}

export function createMouseHandler(
  viewer: Viewer,
  onMove: (coords: { longitude: number; latitude: number; height: number } | null) => void,
  onClick?: (coords: { longitude: number; latitude: number; height: number }) => void,
): ScreenSpaceEventHandler {
  const handler = new ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((movement: { endPosition: Cartesian2 }) => {
    onMove(pickCoords(viewer, movement.endPosition));
  }, ScreenSpaceEventType.MOUSE_MOVE);

  if (onClick) {
    handler.setInputAction((click: { position: Cartesian2 }) => {
      const coords = pickCoords(viewer, click.position);
      if (coords) onClick(coords);
    }, ScreenSpaceEventType.LEFT_CLICK);
  }
  return handler;
}

export function addRasterOverlay(viewer: Viewer, layerId: string, apiBase: string): ImageryLayer {
  const provider = new UrlTemplateImageryProvider({
    url: `${apiBase}/raster/tiles/${layerId}/{z}/{x}/{y}.png`,
    maximumLevel: 12,
  });
  return viewer.imageryLayers.addImageryProvider(provider);
}

export { Cartesian3, Color, CesiumMath, ScreenSpaceEventType, Cartographic, sampleTerrainMostDetailed };
