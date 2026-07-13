import { useEffect, useRef } from 'react';
import {
  createEarthVisionViewer,
  createMouseHandler,
  flyTo,
  renderSceneFootprints,
  setAoiEntity,
  addMarkerEntity,
  type ViewerHandles,
} from './cesiumViewer';
import { useMapStore } from '../store/mapStore';
import type { Viewer } from 'cesium';

export interface GlobeController {
  flyTo: (lon: number, lat: number, height?: number) => void;
  getViewer: () => Viewer | null;
  getHandles: () => ViewerHandles | null;
}

interface GlobeProps {
  onReady?: (controller: GlobeController) => void;
}

export function Globe({ onReady }: GlobeProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const handlesRef = useRef<ViewerHandles | null>(null);
  const {
    scenes,
    footprintsVisible,
    aoiGeoJson,
    markers,
    setMouseCoords,
    setCameraHeading,
  } = useMapStore();

  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;
    let handler: { destroy: () => void } | null = null;
    let headingInterval: number | undefined;

    createEarthVisionViewer(containerRef.current).then((handles) => {
      if (cancelled) {
        handles.destroy();
        return;
      }
      handlesRef.current = handles;
      handler = createMouseHandler(handles.viewer, (coords) => setMouseCoords(coords));

      headingInterval = window.setInterval(() => {
        if (!handles.viewer.isDestroyed()) {
          const heading =
            (handles.viewer.camera.heading * 180) / Math.PI;
          setCameraHeading(((heading % 360) + 360) % 360);
        }
      }, 200);

      onReady?.({
        flyTo: (lon, lat, height) => flyTo(handles.viewer, lon, lat, height),
        getViewer: () => handles.viewer,
        getHandles: () => handlesRef.current,
      });
    });

    return () => {
      cancelled = true;
      if (headingInterval) window.clearInterval(headingInterval);
      handler?.destroy();
      handlesRef.current?.destroy();
      handlesRef.current = null;
    };
  }, [onReady, setMouseCoords, setCameraHeading]);

  useEffect(() => {
    const handles = handlesRef.current;
    if (!handles) return;
    if (footprintsVisible) {
      renderSceneFootprints(handles.footprints, scenes);
    } else {
      handles.footprints.entities.removeAll();
    }
  }, [scenes, footprintsVisible]);

  useEffect(() => {
    const handles = handlesRef.current;
    if (!handles) return;
    setAoiEntity(handles.aoi, aoiGeoJson);
  }, [aoiGeoJson]);

  useEffect(() => {
    const handles = handlesRef.current;
    if (!handles) return;
    handles.markers.entities.removeAll();
    for (const marker of markers) {
      addMarkerEntity(handles.markers, marker.lon, marker.lat, marker.label);
    }
  }, [markers]);

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 h-full w-full"
      id="earthvision-globe"
    />
  );
}
