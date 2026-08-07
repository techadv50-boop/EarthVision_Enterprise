import { useEffect, useRef } from 'react';
import * as Cesium from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { useMapStore } from '@/store/mapStore';
import { offlineApi } from '@/services/api';
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
      if (destroyed || !containerRef.current) return;

      // Fully offline: no Cesium Ion terrain / imagery
      Cesium.Ion.defaultAccessToken = '';

      const offlineBasemap = new Cesium.UrlTemplateImageryProvider({
        url: '/api/v1/offline/basemap/{z}/{x}/{y}.png?style=satellite',
        tilingScheme: new Cesium.WebMercatorTilingScheme(),
        maximumLevel: 10,
        credit: new Cesium.Credit('SAT EYE Offline Basemap'),
      });

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
        baseLayer: new Cesium.ImageryLayer(offlineBasemap),
        terrainProvider: new Cesium.EllipsoidTerrainProvider(),
        scene3DOnly: false,
        requestRenderMode: false,
      });

      // Ensure only the offline basemap remains (no Ion defaults)
      const imagery = viewer.imageryLayers;
      while (imagery.length > 1) {
        imagery.remove(imagery.get(0), true);
      }
      if (imagery.length === 0) {
        imagery.addImageryProvider(offlineBasemap);
      }

      viewer.scene.globe.enableLighting = true;
      viewer.scene.globe.depthTestAgainstTerrain = false;
      viewer.scene.fog.enabled = true;
      viewer.scene.fog.density = 2.0e-4;
      viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString('#0b1220');
      viewer.scene.backgroundColor = Cesium.Color.fromCssColorString('#070b14');

      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(20.0, 15.0, 16000000),
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

      // Seed landmarks on globe for offline context
      try {
        const { data } = await offlineApi.layerGeojson('landmarks');
        for (const f of data.features || []) {
          if (f.geometry?.type !== 'Point') continue;
          const [lon, lat] = f.geometry.coordinates;
          const props = f.properties || {};
          viewer.entities.add({
            name: props.name,
            position: Cesium.Cartesian3.fromDegrees(lon, lat),
            point: {
              pixelSize: props.type === 'city' ? 5 : 7,
              color:
                props.type === 'peak'
                  ? Cesium.Color.fromCssColorString('#5eead4')
                  : Cesium.Color.fromCssColorString('#fbbf24'),
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 1,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            label: {
              text: props.name,
              font: '11px Space Grotesk, sans-serif',
              fillColor: Cesium.Color.WHITE,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 3,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
              pixelOffset: new Cesium.Cartesian2(0, -10),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
              distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 8.0e6),
            },
          });
        }
      } catch {
        /* landmarks optional at boot */
      }

      handler.setInputAction((click: { position: Cesium.Cartesian2 }) => {
        const picked = viewer.scene.pick(click.position);
        if (picked?.id?.name) {
          showNotification(String(picked.id.name), 'info');
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
