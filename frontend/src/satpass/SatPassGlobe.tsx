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
  swathKm: number;
  noradId?: number | null;
}

interface Props {
  sats: TrackedSat[];
  onStates?: (states: Record<number, SatState>) => void;
  focusId?: number | null;
  /** Also draw the large radio line-of-sight (visibility) circle. */
  showVisibility?: boolean;
}

interface SatRuntime {
  satrec: SatRec;
  color: Cesium.Color;
  state: SatState | null;
  swathKm: number;
  entities: Cesium.Entity[];
  visEntity: Cesium.Entity | null;
  trackEntities: Cesium.Entity[];
}

export default function SatPassGlobe({ sats, onStates, focusId, showVisibility = false }: Props) {
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
      // Default to a simple flat 2D map; the scene-mode picker can switch to 3D.
      sceneMode: Cesium.SceneMode.SCENE2D,
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

    viewer.scene.globe.enableLighting = false;
    if (viewer.scene.skyAtmosphere) viewer.scene.skyAtmosphere.show = false;
    viewer.clock.shouldAnimate = true;
    viewer.clock.multiplier = 1;
    // Frame the whole world (works in both 2D and 3D).
    viewer.camera.setView({
      destination: Cesium.Rectangle.fromDegrees(-180, -80, 180, 80),
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
        if (rt.visEntity) viewer.entities.remove(rt.visEntity);
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
        rt = {
          satrec,
          color,
          state: null,
          swathKm: sat.swathKm,
          entities: [],
          visEntity: null,
          trackEntities: [],
        };
        const date = Cesium.JulianDate.toDate(viewer.clock.currentTime);
        rt.state = getState(satrec, date);

        const runtimeRt = rt;
        const subPosition = new Cesium.CallbackPositionProperty(() => {
          const s = runtimeRt.state;
          return s ? Cesium.Cartesian3.fromDegrees(s.lon, s.lat, 0) : undefined;
        }, false);
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

        // Sub-satellite point: where the satellite is focusing on Earth.
        const subEntity = viewer.entities.add({
          position: subPosition,
          point: {
            pixelSize: 6,
            color: Cesium.Color.YELLOW,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 1,
          },
        });

        // Imaging swath: a small circle sized by the (editable) swath width.
        const swathEntity = viewer.entities.add({
          position: subPosition,
          ellipse: {
            semiMajorAxis: new Cesium.CallbackProperty(
              () => (runtimeRt.swathKm * 1000) / 2,
              false,
            ),
            semiMinorAxis: new Cesium.CallbackProperty(
              () => (runtimeRt.swathKm * 1000) / 2,
              false,
            ),
            material: color.withAlpha(0.35),
            outline: true,
            outlineColor: color.withAlpha(0.9),
            height: 0,
          },
        });

        // Optional radio line-of-sight (visibility) circle — large.
        const visEntity = viewer.entities.add({
          position: subPosition,
          ellipse: {
            semiMajorAxis: new Cesium.CallbackProperty(
              () => (runtimeRt.state ? footprintRadiusMeters(runtimeRt.state.altKm) : 0),
              false,
            ),
            semiMinorAxis: new Cesium.CallbackProperty(
              () => (runtimeRt.state ? footprintRadiusMeters(runtimeRt.state.altKm) : 0),
              false,
            ),
            material: color.withAlpha(0.08),
            outline: true,
            outlineColor: color.withAlpha(0.4),
            height: 0,
          },
        });

        rt.entities = [satEntity, subEntity, swathEntity];
        rt.visEntity = visEntity;
        refreshTrack(viewer, rt, date);
        runtime.set(sat.id, rt);
      } else {
        rt.color = color;
      }

      rt.swathKm = sat.swathKm;
      const show = sat.visible;
      rt.entities.forEach((e) => (e.show = show));
      rt.trackEntities.forEach((e) => (e.show = show));
      if (rt.visEntity) rt.visEntity.show = show && showVisibility;
    }
  }, [sats, showVisibility]);

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
