import { useEffect, useRef } from 'react';
import * as Cesium from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { parseTle, getState, groundTrack, footprintRadiusMeters, type SatState } from './orbit';
import type { SatRec } from 'satellite.js';

export interface TrackedSat {
  id: number;
  name: string;
  line1: string;
  line2: string;
  color: string;
  visible: boolean;
  noradId?: number | null;
}

interface Props {
  sats: TrackedSat[];
  onStates?: (states: Record<number, SatState>) => void;
  focusId?: number | null;
}

interface SatRuntime {
  satrec: SatRec;
  color: Cesium.Color;
  state: SatState | null;
  entities: Cesium.Entity[];
  trackEntities: Cesium.Entity[];
}

export default function SatPassGlobe({ sats, onStates, focusId }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Cesium.Viewer | null>(null);
  const runtimeRef = useRef<Map<number, SatRuntime>>(new Map());
  const lastTrackRef = useRef(0);
  const lastEmitRef = useRef(0);

  // Create the Cesium viewer once.
  useEffect(() => {
    if (!containerRef.current || viewerRef.current) return;

    if (import.meta.env.VITE_CESIUM_ION_TOKEN) {
      Cesium.Ion.defaultAccessToken = import.meta.env.VITE_CESIUM_ION_TOKEN as string;
    }

    // Token-free base map: Cesium ships an offline Natural Earth II world texture.
    const baseLayer = Cesium.ImageryLayer.fromProviderAsync(
      Cesium.TileMapServiceImageryProvider.fromUrl(
        Cesium.buildModuleUrl('Assets/Textures/NaturalEarthII'),
      ),
      {},
    );

    const viewer = new Cesium.Viewer(containerRef.current, {
      baseLayer,
      animation: true,
      timeline: true,
      baseLayerPicker: false,
      geocoder: false,
      homeButton: true,
      sceneModePicker: true,
      navigationHelpButton: false,
      fullscreenButton: true,
      infoBox: false,
      selectionIndicator: false,
    });

    viewer.scene.globe.enableLighting = true;
    if (viewer.scene.skyAtmosphere) viewer.scene.skyAtmosphere.show = true;
    viewer.clock.shouldAnimate = true;
    viewer.clock.multiplier = 1;
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(0, 10, 30_000_000),
    });

    const onTick = () => {
      const date = Cesium.JulianDate.toDate(viewer.clock.currentTime);
      const runtime = runtimeRef.current;
      const states: Record<number, SatState> = {};
      runtime.forEach((rt, id) => {
        rt.state = getState(rt.satrec, date);
        if (rt.state) states[id] = rt.state;
      });

      const nowMs = performance.now();
      if (onStates && nowMs - lastEmitRef.current > 300) {
        lastEmitRef.current = nowMs;
        onStates(states);
      }
      // Refresh ground tracks periodically as the clock advances.
      if (nowMs - lastTrackRef.current > 2000) {
        lastTrackRef.current = nowMs;
        runtime.forEach((rt) => refreshTrack(viewer, rt, date));
      }
    };
    viewer.clock.onTick.addEventListener(onTick);

    viewerRef.current = viewer;

    return () => {
      viewer.clock.onTick.removeEventListener(onTick);
      viewer.destroy();
      viewerRef.current = null;
      runtimeRef.current.clear();
    };
  }, [onStates]);

  // Sync satellite entities with the tracked list.
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const runtime = runtimeRef.current;
    const wanted = new Set(sats.map((s) => s.id));

    // Remove satellites that are no longer tracked.
    runtime.forEach((rt, id) => {
      if (!wanted.has(id)) {
        rt.entities.forEach((e) => viewer.entities.remove(e));
        rt.trackEntities.forEach((e) => viewer.entities.remove(e));
        runtime.delete(id);
      }
    });

    for (const sat of sats) {
      let rt = runtime.get(sat.id);
      const color = Cesium.Color.fromCssColorString(sat.color) ?? Cesium.Color.CYAN;

      if (!rt) {
        let satrec: SatRec;
        try {
          satrec = parseTle(sat.line1, sat.line2);
        } catch {
          continue;
        }
        rt = { satrec, color, state: null, entities: [], trackEntities: [] };
        const date = Cesium.JulianDate.toDate(viewer.clock.currentTime);
        rt.state = getState(satrec, date);

        const runtimeRt = rt;
        // Satellite position (above the surface).
        const satEntity = viewer.entities.add({
          position: new Cesium.CallbackPositionProperty(() => {
            const s = runtimeRt.state;
            return s
              ? Cesium.Cartesian3.fromDegrees(s.lon, s.lat, s.altKm * 1000)
              : undefined;
          }, false),
          point: {
            pixelSize: 12,
            color,
            outlineColor: Cesium.Color.WHITE,
            outlineWidth: 2,
          },
          label: {
            text: new Cesium.CallbackProperty(() => {
              const s = runtimeRt.state;
              if (!s) return sat.name;
              return `${sat.name}\n${s.lat.toFixed(2)}, ${s.lon.toFixed(2)}  ·  ${s.altKm.toFixed(0)} km`;
            }, false),
            font: '13px Inter, sans-serif',
            fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 3,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            pixelOffset: new Cesium.Cartesian2(0, -20),
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            showBackground: true,
            backgroundColor: new Cesium.Color(0, 0, 0, 0.55),
          },
        });

        // Sub-satellite point (where it is focusing on Earth) + footprint circle.
        const footprintEntity = viewer.entities.add({
          position: new Cesium.CallbackPositionProperty(() => {
            const s = runtimeRt.state;
            return s ? Cesium.Cartesian3.fromDegrees(s.lon, s.lat, 0) : undefined;
          }, false),
          point: {
            pixelSize: 6,
            color: Cesium.Color.YELLOW,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 1,
          },
          ellipse: {
            semiMajorAxis: new Cesium.CallbackProperty(
              () => (runtimeRt.state ? footprintRadiusMeters(runtimeRt.state.altKm) : 0),
              false,
            ),
            semiMinorAxis: new Cesium.CallbackProperty(
              () => (runtimeRt.state ? footprintRadiusMeters(runtimeRt.state.altKm) : 0),
              false,
            ),
            material: color.withAlpha(0.18),
            outline: true,
            outlineColor: color.withAlpha(0.8),
            height: 0,
          },
        });

        rt.entities = [satEntity, footprintEntity];
        refreshTrack(viewer, rt, date);
        runtime.set(sat.id, rt);
      } else {
        rt.color = color;
      }

      const show = sat.visible;
      rt.entities.forEach((e) => (e.show = show));
      rt.trackEntities.forEach((e) => (e.show = show));
    }
  }, [sats]);

  // Fly to a satellite when requested.
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || focusId == null) return;
    const rt = runtimeRef.current.get(focusId);
    if (!rt?.state) return;
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(
        rt.state.lon,
        rt.state.lat,
        Math.max(rt.state.altKm * 1000 * 4, 8_000_000),
      ),
      duration: 1.2,
    });
  }, [focusId]);

  return <div ref={containerRef} className="absolute inset-0 h-full w-full" />;
}

function refreshTrack(viewer: Cesium.Viewer, rt: SatRuntime, date: Date) {
  const show = rt.entities[0]?.show ?? true;
  rt.trackEntities.forEach((e) => viewer.entities.remove(e));
  rt.trackEntities = [];
  const segments = groundTrack(rt.satrec, date);
  for (const seg of segments) {
    if (seg.length < 2) continue;
    const positions = seg.map((p) => Cesium.Cartesian3.fromDegrees(p.lon, p.lat, 0));
    const entity = viewer.entities.add({
      show,
      polyline: {
        positions,
        width: 2,
        material: rt.color.withAlpha(0.85),
        arcType: Cesium.ArcType.GEODESIC,
        clampToGround: false,
      },
    });
    rt.trackEntities.push(entity);
  }
}
