import {
  CallbackProperty,
  Cartesian2,
  Cartesian3,
  Color,
  CustomDataSource,
  Entity,
  HeightReference,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  Viewer,
} from 'cesium';
import { pickCoords } from './cesiumViewer';
import type { DrawMode } from '../store/mapStore';

export interface DrawingController {
  setMode: (mode: DrawMode) => void;
  clear: () => void;
  destroy: () => void;
}

export function createDrawingController(
  viewer: Viewer,
  aoiSource: CustomDataSource,
  onComplete: (feature: GeoJSON.Feature) => void,
): DrawingController {
  const handler = new ScreenSpaceEventHandler(viewer.scene.canvas);
  let mode: DrawMode = 'none';
  let activePositions: Cartesian3[] = [];
  let previewEntity: Entity | null = null;
  let rectangleStart: { lon: number; lat: number } | null = null;
  let circleCenter: { lon: number; lat: number } | null = null;

  const clearPreview = () => {
    if (previewEntity) {
      aoiSource.entities.remove(previewEntity);
      previewEntity = null;
    }
    activePositions = [];
    rectangleStart = null;
    circleCenter = null;
  };

  const finishPolygon = () => {
    if (activePositions.length < 3) return;
    const coords = activePositions.map((p) => {
      const c = pickCoords(
        viewer,
        viewer.scene.cartesianToCanvasCoordinates(p) as Cartesian2,
      );
      // Fallback via Cartographic
      const carto = viewer.scene.globe.ellipsoid.cartesianToCartographic(p);
      const lon = (carto.longitude * 180) / Math.PI;
      const lat = (carto.latitude * 180) / Math.PI;
      return [lon, lat] as [number, number];
    });
    if (coords[0][0] !== coords[coords.length - 1][0] || coords[0][1] !== coords[coords.length - 1][1]) {
      coords.push(coords[0]);
    }
    const feature: GeoJSON.Feature = {
      type: 'Feature',
      properties: { name: 'AOI Polygon', kind: 'polygon' },
      geometry: { type: 'Polygon', coordinates: [coords] },
    };
    clearPreview();
    onComplete(feature);
    mode = 'none';
  };

  handler.setInputAction((click: { position: Cartesian2 }) => {
    const coords = pickCoords(viewer, click.position);
    if (!coords || mode === 'none' || mode === 'measure') return;
    const position = Cartesian3.fromDegrees(coords.longitude, coords.latitude);

    if (mode === 'polygon') {
      activePositions.push(position);
      if (!previewEntity) {
        previewEntity = aoiSource.entities.add({
          polyline: {
            positions: new CallbackProperty(() => activePositions, false),
            width: 2,
            material: Color.fromCssColorString('#c4a574'),
            clampToGround: true,
          },
          polygon: {
            hierarchy: new CallbackProperty(() => activePositions, false),
            material: Color.fromCssColorString('#c4a574').withAlpha(0.2),
            heightReference: HeightReference.CLAMP_TO_GROUND,
          },
        });
      }
    } else if (mode === 'rectangle') {
      if (!rectangleStart) {
        rectangleStart = { lon: coords.longitude, lat: coords.latitude };
      } else {
        const west = Math.min(rectangleStart.lon, coords.longitude);
        const east = Math.max(rectangleStart.lon, coords.longitude);
        const south = Math.min(rectangleStart.lat, coords.latitude);
        const north = Math.max(rectangleStart.lat, coords.latitude);
        const ring: [number, number][] = [
          [west, south],
          [east, south],
          [east, north],
          [west, north],
          [west, south],
        ];
        clearPreview();
        onComplete({
          type: 'Feature',
          properties: { name: 'AOI Rectangle', kind: 'rectangle' },
          geometry: { type: 'Polygon', coordinates: [ring] },
        });
        mode = 'none';
      }
    } else if (mode === 'circle') {
      if (!circleCenter) {
        circleCenter = { lon: coords.longitude, lat: coords.latitude };
      } else {
        const radiusDeg = Math.hypot(
          coords.longitude - circleCenter.lon,
          coords.latitude - circleCenter.lat,
        );
        const ring: [number, number][] = [];
        for (let i = 0; i <= 64; i++) {
          const angle = (i / 64) * Math.PI * 2;
          ring.push([
            circleCenter.lon + radiusDeg * Math.cos(angle),
            circleCenter.lat + radiusDeg * Math.sin(angle),
          ]);
        }
        clearPreview();
        onComplete({
          type: 'Feature',
          properties: { name: 'AOI Circle', kind: 'circle', radiusDeg },
          geometry: { type: 'Polygon', coordinates: [ring] },
        });
        mode = 'none';
      }
    }
  }, ScreenSpaceEventType.LEFT_CLICK);

  handler.setInputAction(() => {
    if (mode === 'polygon') finishPolygon();
  }, ScreenSpaceEventType.LEFT_DOUBLE_CLICK);

  return {
    setMode: (m) => {
      clearPreview();
      mode = m;
    },
    clear: () => {
      clearPreview();
      aoiSource.entities.removeAll();
      mode = 'none';
    },
    destroy: () => {
      clearPreview();
      handler.destroy();
    },
  };
}
