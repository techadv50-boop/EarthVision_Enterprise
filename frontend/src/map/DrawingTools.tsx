import { useEffect, useRef } from 'react';
import * as Cesium from 'cesium';
import type { Feature } from 'geojson';
import { useMapStore, DRAWN_PROP } from '@/store/mapStore';
import { useUIStore } from '@/store/uiStore';

function circleToPolygon(
  lon: number,
  lat: number,
  radiusMeters: number,
  segments = 32
): number[][] {
  const coords: number[][] = [];
  const earthRadius = 6378137;
  const latRad = (lat * Math.PI) / 180;
  const angularDistance = radiusMeters / earthRadius;

  for (let i = 0; i <= segments; i++) {
    const bearing = (2 * Math.PI * i) / segments;
    const lat2 = Math.asin(
      Math.sin(latRad) * Math.cos(angularDistance) +
        Math.cos(latRad) * Math.sin(angularDistance) * Math.cos(bearing)
    );
    const lon2 =
      ((lon * Math.PI) / 180) +
      Math.atan2(
        Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(latRad),
        Math.cos(angularDistance) - Math.sin(latRad) * Math.sin(lat2)
      );
    coords.push([(lon2 * 180) / Math.PI, (lat2 * 180) / Math.PI]);
  }
  return coords;
}

function tagDrawn(entity: Cesium.Entity) {
  entity.properties = entity.properties || new Cesium.PropertyBag({});
  (entity.properties as Cesium.PropertyBag).addProperty(DRAWN_PROP);
  entity.properties[DRAWN_PROP] = true;
}

export default function DrawingTools() {
  const { viewer, activeTool, addGeometry } = useMapStore();
  const { showNotification } = useUIStore();
  const handlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);
  const activeShapeRef = useRef<Cesium.Entity | null>(null);
  const activePointsRef = useRef<Cesium.Cartesian3[]>([]);
  const measurePointsRef = useRef<Cesium.Cartesian3[]>([]);

  useEffect(() => {
    if (!viewer) return;

    if (handlerRef.current) {
      handlerRef.current.destroy();
      handlerRef.current = null;
    }

    if (activeTool === 'navigate') return;

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
    handlerRef.current = handler;

    const getPosition = (position: Cesium.Cartesian2): Cesium.Cartesian3 | undefined => {
      const ray = viewer.camera.getPickRay(position);
      if (!ray) return undefined;
      return viewer.scene.globe.pick(ray, viewer.scene) ?? undefined;
    };

    const createPoint = (worldPosition: Cesium.Cartesian3) => {
      const entity = viewer.entities.add({
        position: worldPosition,
        point: {
          pixelSize: 8,
          color: Cesium.Color.YELLOW,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        },
      });
      tagDrawn(entity);
      return entity;
    };

    const drawShape = (positions: Cesium.Cartesian3[]) => {
      let entity: Cesium.Entity | null = null;
      if (activeTool === 'polygon') {
        entity = viewer.entities.add({
          polygon: {
            hierarchy: positions,
            material: Cesium.Color.BLUE.withAlpha(0.3),
            outline: true,
            outlineColor: Cesium.Color.BLUE,
          },
        });
      } else if (activeTool === 'rectangle' && positions.length >= 2) {
        entity = viewer.entities.add({
          rectangle: {
            coordinates: Cesium.Rectangle.fromCartesianArray(positions),
            material: Cesium.Color.GREEN.withAlpha(0.3),
            outline: true,
            outlineColor: Cesium.Color.GREEN,
          },
        });
      } else if (activeTool === 'circle' && positions.length >= 2) {
        const radius = Cesium.Cartesian3.distance(positions[0], positions[1]);
        entity = viewer.entities.add({
          position: positions[0],
          ellipse: {
            semiMinorAxis: radius,
            semiMajorAxis: radius,
            material: Cesium.Color.ORANGE.withAlpha(0.3),
            outline: true,
            outlineColor: Cesium.Color.ORANGE,
          },
        });
      }
      if (entity) tagDrawn(entity);
      return entity;
    };

    const finishDrawing = () => {
      if (activePointsRef.current.length === 0) return;

      const positions = [...activePointsRef.current];
      let feature: Feature | null = null;

      if (activeTool === 'polygon' && positions.length >= 3) {
        const coords = positions.map((p) => {
          const c = Cesium.Cartographic.fromCartesian(p);
          return [Cesium.Math.toDegrees(c.longitude), Cesium.Math.toDegrees(c.latitude)];
        });
        coords.push(coords[0]);
        feature = {
          type: 'Feature',
          geometry: { type: 'Polygon', coordinates: [coords] },
          properties: { type: 'polygon' },
        };
      } else if (activeTool === 'rectangle' && positions.length >= 2) {
        const c1 = Cesium.Cartographic.fromCartesian(positions[0]);
        const c2 = Cesium.Cartographic.fromCartesian(positions[1]);
        const west = Math.min(
          Cesium.Math.toDegrees(c1.longitude),
          Cesium.Math.toDegrees(c2.longitude)
        );
        const east = Math.max(
          Cesium.Math.toDegrees(c1.longitude),
          Cesium.Math.toDegrees(c2.longitude)
        );
        const south = Math.min(
          Cesium.Math.toDegrees(c1.latitude),
          Cesium.Math.toDegrees(c2.latitude)
        );
        const north = Math.max(
          Cesium.Math.toDegrees(c1.latitude),
          Cesium.Math.toDegrees(c2.latitude)
        );
        feature = {
          type: 'Feature',
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
              ],
            ],
          },
          properties: { type: 'rectangle' },
        };
      } else if (activeTool === 'circle' && positions.length >= 2) {
        const center = Cesium.Cartographic.fromCartesian(positions[0]);
        const lon = Cesium.Math.toDegrees(center.longitude);
        const lat = Cesium.Math.toDegrees(center.latitude);
        const radius = Cesium.Cartesian3.distance(positions[0], positions[1]);
        const ring = circleToPolygon(lon, lat, radius);
        feature = {
          type: 'Feature',
          geometry: { type: 'Polygon', coordinates: [ring] },
          properties: { type: 'circle', radius_m: radius, center: [lon, lat] },
        };
      } else if (activeTool === 'marker' && positions.length >= 1) {
        const c = Cesium.Cartographic.fromCartesian(positions[0]);
        feature = {
          type: 'Feature',
          geometry: {
            type: 'Point',
            coordinates: [
              Cesium.Math.toDegrees(c.longitude),
              Cesium.Math.toDegrees(c.latitude),
            ],
          },
          properties: { type: 'marker' },
        };
        const marker = viewer.entities.add({
          position: positions[0],
          point: {
            pixelSize: 14,
            color: Cesium.Color.RED,
            outlineColor: Cesium.Color.WHITE,
            outlineWidth: 2,
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          },
        });
        tagDrawn(marker);
      }

      if (feature) addGeometry(feature);

      activePointsRef.current = [];
      activeShapeRef.current = null;
    };

    if (activeTool === 'polygon') {
      handler.setInputAction((event: { position: Cesium.Cartesian2 }) => {
        const pos = getPosition(event.position);
        if (!pos) return;
        activePointsRef.current.push(pos);
        createPoint(pos);
        if (activePointsRef.current.length >= 2) {
          if (activeShapeRef.current) viewer.entities.remove(activeShapeRef.current);
          activeShapeRef.current = drawShape(activePointsRef.current);
        }
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

      handler.setInputAction(() => finishDrawing(), Cesium.ScreenSpaceEventType.RIGHT_CLICK);
    } else if (activeTool === 'rectangle' || activeTool === 'circle') {
      let startPoint: Cesium.Cartesian3 | undefined;

      handler.setInputAction((event: { position: Cesium.Cartesian2 }) => {
        const pos = getPosition(event.position);
        if (!pos) return;
        if (!startPoint) {
          startPoint = pos;
          activePointsRef.current = [pos];
          createPoint(pos);
        } else {
          activePointsRef.current = [startPoint, pos];
          if (activeShapeRef.current) viewer.entities.remove(activeShapeRef.current);
          activeShapeRef.current = drawShape(activePointsRef.current);
          finishDrawing();
          startPoint = undefined;
        }
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    } else if (activeTool === 'marker') {
      handler.setInputAction((event: { position: Cesium.Cartesian2 }) => {
        const pos = getPosition(event.position);
        if (!pos) return;
        activePointsRef.current = [pos];
        finishDrawing();
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    } else if (activeTool === 'measure') {
      measurePointsRef.current = [];
      handler.setInputAction((event: { position: Cesium.Cartesian2 }) => {
        const pos = getPosition(event.position);
        if (!pos) return;
        measurePointsRef.current.push(pos);
        createPoint(pos);

        if (measurePointsRef.current.length === 2) {
          const [a, b] = measurePointsRef.current;
          const distance = Cesium.Cartesian3.distance(a, b);
          const line = viewer.entities.add({
            polyline: {
              positions: [a, b],
              width: 3,
              material: Cesium.Color.YELLOW,
              clampToGround: true,
            },
            label: {
              text:
                distance >= 1000
                  ? `${(distance / 1000).toFixed(2)} km`
                  : `${distance.toFixed(1)} m`,
              font: '14px sans-serif',
              fillColor: Cesium.Color.WHITE,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
              pixelOffset: new Cesium.Cartesian2(0, -12),
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            },
            position: Cesium.Cartesian3.midpoint(a, b, new Cesium.Cartesian3()),
          });
          tagDrawn(line);
          showNotification(
            distance >= 1000
              ? `Distance: ${(distance / 1000).toFixed(2)} km`
              : `Distance: ${distance.toFixed(1)} m`,
            'info'
          );
          measurePointsRef.current = [];
        }
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    }

    return () => {
      handler.destroy();
      handlerRef.current = null;
    };
  }, [viewer, activeTool, addGeometry, showNotification]);

  return null;
}
