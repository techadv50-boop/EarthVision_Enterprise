import { useEffect, useRef } from 'react';
import * as Cesium from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { useMapStore } from '@/store/mapStore';
import { configApi, geoApi } from '@/services/api';
import { useUIStore } from '@/store/uiStore';

interface GlobeViewerProps {
  onReady?: (viewer: Cesium.Viewer) => void;
}

export default function GlobeViewer({ onReady }: GlobeViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Cesium.Viewer | null>(null);
  const { setViewer, setMousePosition } = useMapStore();
  const { showNotification } = useUIStore();

  useEffect(() => {
    if (!containerRef.current || viewerRef.current) return;

    let destroyed = false;
    let handler: Cesium.ScreenSpaceEventHandler | null = null;

    const init = async () => {
      try {
        const { data } = await configApi.config();
        if (data.cesium_ion_token) {
          Cesium.Ion.defaultAccessToken = data.cesium_ion_token;
        } else if (import.meta.env.VITE_CESIUM_ION_TOKEN) {
          Cesium.Ion.defaultAccessToken = import.meta.env.VITE_CESIUM_ION_TOKEN;
        } else {
          Cesium.Ion.defaultAccessToken =
            'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJlYWE1OWUxNy1mMWZiLTQzYjYtYTQ0OS1kMWFjYmFkNjc5YzciLCJpZCI6NTc3MzMsImlhdCI6MTYyMjY0NjQ5OH0.XcKpgNzNQiymHgoU0PEGYkep7S9Gj0CGAy7A0pxE5Y';
        }
      } catch {
        Cesium.Ion.defaultAccessToken =
          import.meta.env.VITE_CESIUM_ION_TOKEN ||
          'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJlYWE1OWUxNy1mMWZiLTQzYjYtYTQ0OS1kMWFjYmFkNjc5YzciLCJpZCI6NTc3MzMsImlhdCI6MTYyMjY0NjQ5OH0.XcKpgNzNQiymHgoU0PEGYkep7S9Gj0CGAy7A0pxE5Y';
      }

      if (destroyed || !containerRef.current) return;

      const viewer = new Cesium.Viewer(containerRef.current, {
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
        terrain: Cesium.Terrain.fromWorldTerrain(),
        scene3DOnly: false,
      });

      viewer.scene.globe.enableLighting = true;
      viewer.scene.globe.depthTestAgainstTerrain = true;
      viewer.scene.fog.enabled = true;
      viewer.scene.fog.density = 2.0e-4;

      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(-98.0, 39.0, 15000000),
      });

      handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
      handler.setInputAction((movement: { endPosition: Cesium.Cartesian2 }) => {
        const cartesian = viewer.camera.pickEllipsoid(
          movement.endPosition,
          viewer.scene.globe.ellipsoid,
        );
        if (cartesian) {
          const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
          setMousePosition({
            longitude: Cesium.Math.toDegrees(cartographic.longitude),
            latitude: Cesium.Math.toDegrees(cartographic.latitude),
            altitude: cartographic.height,
          });
        }
      }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

      handler.setInputAction(async (click: { position: Cesium.Cartesian2 }) => {
        const cartesian = viewer.camera.pickEllipsoid(
          click.position,
          viewer.scene.globe.ellipsoid,
        );
        if (!cartesian) return;
        const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
        const lon = Cesium.Math.toDegrees(cartographic.longitude);
        const lat = Cesium.Math.toDegrees(cartographic.latitude);
        try {
          const { data } = await geoApi.reverse(lon, lat);
          const label = data.display_name || data.name || `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
          showNotification(label, 'info');
        } catch {
          /* reverse geocode optional */
        }
      }, Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);

      viewerRef.current = viewer;
      setViewer(viewer);
      onReady?.(viewer);
    };

    void init();

    return () => {
      destroyed = true;
      handler?.destroy();
      if (viewerRef.current) {
        viewerRef.current.destroy();
        viewerRef.current = null;
      }
      setViewer(null);
    };
  }, [setViewer, setMousePosition, onReady, showNotification]);

  return <div ref={containerRef} className="absolute inset-0 w-full h-full" />;
}
