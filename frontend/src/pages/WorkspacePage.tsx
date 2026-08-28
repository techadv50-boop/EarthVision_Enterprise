import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { LogOut, Shield, Wrench } from 'lucide-react';
import { LightMap } from '../map/LightMap';
import { MapToolbar } from '../components/map/MapToolbar';
import { MapLegend } from '../components/map/MapLegend';
import {
  PlaceStep,
  SATELLITE_OPTIONS,
  type CatalogFilters,
} from '../components/workflow/PlaceStep';
import { ScenesStep } from '../components/workflow/ScenesStep';
import { ToolboxPanel } from '../components/workflow/ToolboxPanel';
import { AdminPanel } from '../components/admin/AdminPanel';
import { useAuthStore } from '../store/authStore';
import {
  useWorkflowStore,
  type DrawnFeature,
  type MapTool,
  type PlaceSelection,
} from '../store/workflowStore';
import { catalogService, type SceneSummary } from '../services/catalogService';
import {
  analyticsService,
  type IndexName,
  type LegendInfo,
  type ColormapName,
} from '../services/analyticsService';
import {
  compositeService,
  type CompositePreset,
  type CompositeResult,
  type StretchResult,
} from '../services/compositeService';
import {
  classificationService,
  type ClassificationResult,
} from '../services/classificationService';
import {
  terrainService,
  type TerrainProduct,
} from '../services/terrainService';
import { detectionService } from '../services/detectionService';
import { gisService } from '../services/gisService';
import { getErrorMessage } from '../services/api';
import { footprintBbox } from '../utils/geoMath';
import { exportMapJpeg } from '../utils/exportMap';
import type { ToolboxId, ToolboxTool } from '../toolbox/catalog';
import { bookmarkService } from '../services/bookmarkService';
import { HIGH_RES_ONLY_TOOLBOXES, TOOLBOXES } from '../toolbox/catalog';

function sceneBounds(
  scene: SceneSummary,
  place: PlaceSelection | null,
): [number, number, number, number] {
  return (
    footprintBbox(scene.footprint as GeoJSON.Geometry | null, place?.bbox) ??
    place?.bbox ?? [74.15, 31.35, 74.55, 31.7]
  );
}

/** Sensors with no optical Image Processing pipeline in this app. */
function opticalProcessingBlockReason(collection?: string | null): string | null {
  const c = (collection || '').toUpperCase().replace(/_/g, '-');
  if (!c) return null;
  if (c.includes('SENTINEL-1') || c.startsWith('S1')) {
    return 'Sentinel-1 SAR does not support optical Image Processing tools. Use Sentinel-2 or Landsat.';
  }
  if (
    c.includes('SENTINEL-3') ||
    c === 'S3' ||
    c === 'OLCI' ||
    c === 'SLSTR' ||
    c.startsWith('S3-')
  ) {
    return 'Sentinel-3 is not wired for land optical composites/indices in this app. Use Sentinel-2 or Landsat.';
  }
  if (c.includes('SENTINEL-5') || c.includes('S5P')) {
    return 'Sentinel-5P atmospheric products do not support land optical Image Processing tools.';
  }
  if (c.includes('SMOS')) {
    return 'SMOS does not support optical Image Processing tools. Use Sentinel-2 or Landsat.';
  }
  return null;
}

/** Ship Detection: Landsat / Sentinel-2 optical only. */
function opticalShipBlockReason(
  hasScene: boolean,
  collection?: string | null,
): string | null {
  if (!hasScene) {
    return 'Ship Detection stays off until you select a Landsat or Sentinel-2 image (turn the eye on).';
  }
  const c = (collection || '').toUpperCase().replace(/_/g, '-');
  if (!c) {
    return 'Ship Detection requires a Landsat or Sentinel-2 optical scene.';
  }
  if (c.includes('SENTINEL-1') || c.startsWith('S1')) {
    return 'Ship Detection (optical) does not support Sentinel-1 SAR. Use Sentinel-2 or Landsat.';
  }
  const ok =
    c.includes('SENTINEL-2') ||
    c.startsWith('S2') ||
    c.includes('LANDSAT') ||
    c.startsWith('L8') ||
    c.startsWith('L9') ||
    c.startsWith('L7');
  if (!ok) {
    return 'Ship Detection works only with Landsat and Sentinel-2 optical imagery.';
  }
  return null;
}

function aoiBbox(
  aoi: GeoJSON.Feature | null,
  fallback: [number, number, number, number],
): [number, number, number, number] {
  if (aoi?.geometry.type === 'Polygon') {
    const ring = aoi.geometry.coordinates[0];
    const lons = ring.map((c) => c[0]);
    const lats = ring.map((c) => c[1]);
    return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
  }
  return fallback;
}

const CHANGE_INDEX: Record<string, IndexName> = {
  two: 'NDVI',
  multi: 'NDVI',
  urban: 'NDBI',
  forest_loss: 'NDVI',
  forest_gain: 'NDVI',
  agriculture: 'SAVI',
  water: 'NDWI',
  river: 'NDWI',
  coastal: 'NDWI',
  shoreline: 'NDWI',
  flood: 'NDWI',
  burn: 'NBR',
  construction: 'NDBI',
  infra: 'NDBI',
  report: 'NDVI',
  stats: 'NDVI',
};

export function WorkspacePage() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const mapHostRef = useRef<HTMLDivElement>(null);
  const [exporting, setExporting] = useState(false);
  const [toolLoading, setToolLoading] = useState(false);
  const [toolStatus, setToolStatus] = useState<string | null>(null);
  const [activeToolId, setActiveToolId] = useState<string | null>(null);
  const [lastLegend, setLastLegend] = useState<LegendInfo | null>(null);
  const [lastMessage, setLastMessage] = useState<string | null>(null);
  const [bufferLoading, setBufferLoading] = useState(false);
  const [lastBufferDistance, setLastBufferDistance] = useState<number | null>(null);
  const [lastBufferArea, setLastBufferArea] = useState<number | null>(null);
  const [mapCommand, setMapCommand] = useState<{ id: number; type: string } | null>(null);
  const [compositeResult, setCompositeResult] = useState<CompositeResult | null>(null);
  const [classificationResult, setClassificationResult] =
    useState<ClassificationResult | null>(null);
  const [stretchResult, setStretchResult] = useState<StretchResult | null>(null);
  const [stretchParams, setStretchParams] = useState({
    p_low: 2,
    p_high: 98,
    gamma: 1.2,
    brightness: 1.05,
    contrast: 1.05,
  });
  const [processFilter, setProcessFilter] = useState({
    brightness: 1,
    contrast: 1,
    gamma: 1,
  });
  const [selectedColormap, setSelectedColormap] = useState<ColormapName | null>(null);
  const [adminOpen, setAdminOpen] = useState(false);
  const [adminTab, setAdminTab] = useState<'satellites' | 'clients'>('clients');
  const [satelliteRefreshKey, setSatelliteRefreshKey] = useState(0);
  const [geotiffBusy, setGeotiffBusy] = useState(false);
  const [catalogFilters, setCatalogFilters] = useState<CatalogFilters>(() => {
    const end = new Date();
    const start = new Date();
    start.setUTCDate(start.getUTCDate() - 90);
    const defaultSat = SATELLITE_OPTIONS[0];
    return {
      satelliteId: '',
      satelliteLabel: '',
      collections: defaultSat.collections,
      isHighResolution: false,
      startDate: start.toISOString().slice(0, 10),
      endDate: end.toISOString().slice(0, 10),
    };
  });
  const [geotiffLayerId, setGeotiffLayerId] = useState<string | null>(null);

  const isAdmin = user?.role === 'admin';
  const allowedTools =
    isAdmin || user?.allowed_tools == null ? null : user.allowed_tools;

  const {
    step,
    place,
    scenes,
    visibleSceneIds,
    focusSceneId,
    toolboxOpen,
    expandedToolbox,
    mapChrome,
    compareSceneId,
    indexResult,
    changeResult,
    loadingScenes,
    loadingOverlayIds,
    error,
    mapTool,
    aoiGeoJson,
    drawnFeature,
    measureLine,
    bufferGeoJson,
    measureLabel,
    overlays,
    layerOpacity,
    setPlace,
    setScenes,
    setFocusSceneId,
    setToolboxOpen,
    setExpandedToolbox,
    toggleMapChrome,
    setCompareSceneId,
    setIndexResult,
    setChangeResult,
    setSelectedIndex,
    setLoadingScenes,
    addLoadingOverlay,
    removeLoadingOverlay,
    setError,
    setStep,
    setMapTool,
    setAoiGeoJson,
    setDrawnFeature,
    setMeasureLine,
    setBufferGeoJson,
    setMeasureLabel,
    upsertOverlay,
    removeOverlay,
    removeSceneOverlay,
    removeOverlaysByKind,
    setOverlayVisible,
    renameOverlay,
    moveOverlay,
    reorderOverlaysDisplay,
    patchOverlay,
    duplicateOverlay,
    setLayerOpacity,
    showScene,
    hideScene,
    clearAnalysis,
    clearDrawn,
    resetFromPlace,
    backToPlace,
  } = useWorkflowStore();

  // Recover from stale HMR / old store snapshots missing new fields
  useEffect(() => {
    const state = useWorkflowStore.getState();
    const patch: Record<string, unknown> = {};
    if (typeof state.toolboxOpen !== 'boolean') patch.toolboxOpen = true;
    if (!state.expandedToolbox) patch.expandedToolbox = 'image';
    if (!state.mapChrome || typeof state.mapChrome !== 'object') {
      patch.mapChrome = {
        compass: true,
        scaleBar: true,
        coordinates: true,
        grid: true,
        miniMap: false,
        swipe: false,
        splitView: false,
        syncMaps: false,
        rotate: false,
        view3d: false,
        terrainRelief: false,
        timeSlider: false,
        bookmarks: false,
        manualVerify: false,
      };
    } else if (typeof (state.mapChrome as { grid?: boolean }).grid !== 'boolean') {
      patch.mapChrome = { ...state.mapChrome, grid: true };
    }
    // Always reopen toolboxes after login so the new UI is visible
    if (state.toolboxOpen === false) patch.toolboxOpen = true;
    if (Object.keys(patch).length) {
      useWorkflowStore.setState(patch as Partial<typeof state>);
    }
  }, []);

  const focusScene = useMemo(
    () => scenes.find((s) => s.id === focusSceneId) ?? null,
    [scenes, focusSceneId],
  );

  const hasVisibleScene = visibleSceneIds.length > 0;

  const satelliteActive = Boolean(catalogFilters.satelliteId);

  const toolCount = useMemo(() => {
    // Count includes AI / Change / Maritime / Air (visible but always inactive).
    const boxes =
      allowedTools == null
        ? TOOLBOXES
        : TOOLBOXES.filter(
            (b) =>
              allowedTools.includes(b.id) ||
              HIGH_RES_ONLY_TOOLBOXES.includes(b.id),
          );
    return boxes.reduce((n, b) => n + b.tools.length, 0);
  }, [allowedTools]);

  const analysisBbox = useMemo((): [number, number, number, number] => {
    // Processed overlays must match the original scene extent on the map.
    // Prefer the loaded scene layer bounds / STAC footprint, not the place pin AOI
    // (place bbox is only a search window and was clipping false/true color to a small inset).
    const sceneOverlay = focusScene
      ? overlays.find((o) => o.kind === 'scene' && o.sceneId === focusScene.id)
      : null;
    if (sceneOverlay?.bounds) return sceneOverlay.bounds;
    if (focusScene) return sceneBounds(focusScene, place);
    if (place || aoiGeoJson) {
      const fallback = (place?.bbox ??
        ([74.15, 31.35, 74.55, 31.7] as [number, number, number, number]));
      return aoiBbox(aoiGeoJson, fallback);
    }
    return [74.15, 31.35, 74.55, 31.7];
  }, [aoiGeoJson, focusScene, overlays, place]);

  const loadScenesForPlace = useCallback(
    async (selected: PlaceSelection, filters: CatalogFilters) => {
      if (!filters.satelliteId || !filters.collections.length) {
        setError('Select a satellite first');
        return;
      }
      if (!filters.startDate || !filters.endDate) {
        setError('Choose a From and To date for scenes');
        return;
      }
      if (filters.startDate > filters.endDate) {
        setError('From date must be on or before To date');
        return;
      }
      setCatalogFilters(filters);
      setPlace(selected);
      resetFromPlace();
      setLoadingScenes(true);
      setError(null);
      try {
        const bbox = aoiBbox(aoiGeoJson, selected.bbox);
        const result = await catalogService.search({
          collections: filters.collections,
          start_date: `${filters.startDate}T00:00:00.000Z`,
          end_date: `${filters.endDate}T23:59:59.000Z`,
          cloud_cover_max: 80,
          bbox: [...bbox],
          max_results: 20,
        });
        setScenes(result.items.slice(0, 20));
        setStep('browse');
      } catch (err) {
        setError(getErrorMessage(err));
        setStep('browse');
      } finally {
        setLoadingScenes(false);
      }
    },
    [aoiGeoJson, resetFromPlace, setError, setLoadingScenes, setPlace, setScenes, setStep],
  );

  const onPlaceClick = useCallback(
    async (lon: number, lat: number) => {
      if (step !== 'place') return;
      if (mapTool !== 'navigate') return;
      if (!catalogFilters.satelliteId) {
        setError('Select a satellite first');
        return;
      }
      if (!catalogFilters.startDate || !catalogFilters.endDate) {
        setError('Choose a From and To date for scenes');
        return;
      }
      if (catalogFilters.startDate > catalogFilters.endDate) {
        setError('From date must be on or before To date');
        return;
      }
      const pad = 0.18;
      try {
        const reverse = await gisService.reverseGeocode(lon, lat);
        await loadScenesForPlace(
          {
            name: reverse.display_name || `Point ${lat.toFixed(3)}, ${lon.toFixed(3)}`,
            longitude: lon,
            latitude: lat,
            bbox: [lon - pad, lat - pad, lon + pad, lat + pad],
          },
          catalogFilters,
        );
      } catch {
        await loadScenesForPlace(
          {
            name: `${lat.toFixed(4)}°, ${lon.toFixed(4)}°`,
            longitude: lon,
            latitude: lat,
            bbox: [lon - pad, lat - pad, lon + pad, lat + pad],
          },
          catalogFilters,
        );
      }
    },
    [catalogFilters, loadScenesForPlace, mapTool, setError, step],
  );

  const onDrawnFeature = useCallback(
    (feature: DrawnFeature) => {
      setDrawnFeature(feature);
      if (feature.type === 'LineString' && feature.geometry.type === 'LineString') {
        setMeasureLine(feature.geometry);
      }
      setBufferGeoJson(null);
      removeOverlaysByKind('buffer');
      setLastBufferDistance(null);
      setLastBufferArea(null);
    },
    [removeOverlaysByKind, setBufferGeoJson, setDrawnFeature, setMeasureLine],
  );

  const loadSceneOverlay = useCallback(
    async (scene: SceneSummary) => {
      addLoadingOverlay(scene.id);
      setError(null);
      try {
        const bounds = sceneBounds(scene, place);
        const overlay = await analyticsService.sceneOverlay({
          scene_id: scene.id,
          collection: scene.collection,
          bbox: bounds,
          footprint: scene.footprint ?? null,
          sensing_time: scene.sensing_time ?? null,
          cloud_cover: scene.cloud_cover ?? null,
        });
        const tileUrl =
          overlay.tile_url || analyticsService.sceneTileUrl(scene.id);
        const coll = (scene.collection || '').toUpperCase();
        const label =
          overlay.label ||
          (coll === 'SENTINEL-1'
            ? 'Sentinel-1 GRD (grayscale)'
            : coll.startsWith('LANDSAT')
              ? `${scene.collection} true-color`
              : coll.includes('MODIS') ||
                  coll === 'TERRA' ||
                  coll === 'AQUA' ||
                  coll === 'TERRAAQUA'
                ? 'MODIS true-color'
                : `${scene.collection} true-color (TCI)`);
        const hasDemBase = useWorkflowStore
          .getState()
          .overlays.some(
            (o) =>
              o.kind === 'terrain' &&
              o.terrainRole === 'base' &&
              o.visible !== false &&
              o.demGrid,
          );
        upsertOverlay({
          id: `scene-${scene.id}`,
          kind: 'scene',
          sceneId: scene.id,
          url: overlay.overlay_base64
            ? analyticsService.toDataUrl(overlay.overlay_base64)
            : '',
          tileUrl,
          bounds: overlay.bounds as [number, number, number, number],
          footprint: (overlay.footprint as GeoJSON.Polygon | null) ?? null,
          // Soft-drape: satellite stays on top of DEM base
          opacity: hasDemBase ? 0.78 : 1,
          label,
          renderMode: overlay.render_mode,
          visible: true,
        });
      } catch (err) {
        setError(getErrorMessage(err));
        hideScene(scene.id);
      } finally {
        removeLoadingOverlay(scene.id);
      }
    },
    [
      addLoadingOverlay,
      hideScene,
      place,
      removeLoadingOverlay,
      setError,
      upsertOverlay,
    ],
  );

  const onToggleEye = async (scene: SceneSummary) => {
    if (visibleSceneIds.includes(scene.id)) {
      hideScene(scene.id);
      removeSceneOverlay(scene.id);
      if (visibleSceneIds.length <= 1) {
        removeOverlaysByKind('index');
        removeOverlaysByKind('change');
      }
      return;
    }
    showScene(scene.id);
    clearAnalysis();
    removeOverlaysByKind('index');
    removeOverlaysByKind('change');
    await loadSceneOverlay(scene);
  };

  const runIndex = async (index: IndexName, colormap?: ColormapName | null) => {
    if (!focusScene) {
      setError('Show a satellite scene first (eye icon)');
      return;
    }
    {
      const blocked = opticalProcessingBlockReason(focusScene.collection);
      if (blocked) {
        setError(blocked);
        return;
      }
    }
    setToolLoading(true);
    setToolStatus(`Computing ${index} on scene…`);
    setError(null);
    try {
      const sceneOverlay = overlays.find(
        (o) => o.kind === 'scene' && o.sceneId === focusScene.id,
      );
      const bounds = sceneOverlay?.bounds ?? sceneBounds(focusScene, place);
      const ramp = colormap ?? selectedColormap;
      const result = await analyticsService.computeIndex(
        index,
        focusScene.id,
        bounds,
        ramp,
      );
      setIndexResult(result);
      setSelectedIndex(index);
      if (result.colormap) {
        setSelectedColormap(result.colormap as ColormapName);
      }
      setLastLegend(result.legend ?? null);
      setLastMessage(
        `${result.formula || index} · ramp ${result.colormap || ramp || 'default'}`,
      );
      if (result.overlay_base64 && result.bounds) {
        upsertOverlay({
          id: `index-${focusScene.id}-${index}`,
          kind: 'index',
          sceneId: focusScene.id,
          url: analyticsService.toDataUrl(result.overlay_base64),
          bounds: result.bounds as [number, number, number, number],
          footprint: sceneOverlay?.footprint ?? null,
          opacity: layerOpacity,
          label: `${index}${result.colormap ? ` (${result.colormap})` : ''}`,
          visible: true,
        });
      }
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setToolLoading(false);
      setToolStatus(null);
    }
  };

  const runChange = async (mode: string) => {
    if (!focusScene) {
      setError('Show a satellite scene first');
      return;
    }
    const others = scenes.filter((s) => s.id !== focusScene.id);
    const before = others.find((s) => visibleSceneIds.includes(s.id)) || others[0];
    if (!before) {
      setError('Need a second scene for change detection — open another eye or select from catalog');
      return;
    }
    setCompareSceneId(before.id);
    setToolLoading(true);
    setToolStatus(`Change detection (${mode})…`);
    setError(null);
    try {
      const index = CHANGE_INDEX[mode] || 'NDVI';
      const sceneOverlay = overlays.find(
        (o) => o.kind === 'scene' && o.sceneId === focusScene.id,
      );
      const bounds = sceneOverlay?.bounds ?? sceneBounds(focusScene, place);
      const result = await analyticsService.changeDetection({
        before_scene_id: before.id,
        after_scene_id: focusScene.id,
        index,
        bbox: bounds,
        threshold: 0.12,
      });
      setChangeResult(result);
      setLastLegend(result.legend);
      setLastMessage(
        `${mode.replaceAll('_', ' ')} · Δ=${result.mean_difference.toFixed(3)} · ${result.significant_pixels} px`,
      );
      upsertOverlay({
        id: `change-${before.id}-${focusScene.id}`,
        kind: 'change',
        sceneId: focusScene.id,
        url: analyticsService.toDataUrl(result.overlay_base64),
        bounds: result.bounds as [number, number, number, number],
        footprint: sceneOverlay?.footprint ?? null,
        opacity: layerOpacity,
        label: `${index} ${mode}`,
        visible: true,
      });
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setToolLoading(false);
      setToolStatus(null);
    }
  };

  const runTerrain = async (product: TerrainProduct) => {
    setToolLoading(true);
    setToolStatus(`Terrain: ${product.replaceAll('_', ' ')}…`);
    setError(null);
    try {
      const line =
        measureLine ||
        (drawnFeature?.type === 'LineString' && drawnFeature.geometry.type === 'LineString'
          ? drawnFeature.geometry
          : null);
      let observer: [number, number] | undefined;
      let target: [number, number] | undefined;
      if (drawnFeature?.type === 'Point' && drawnFeature.geometry.type === 'Point') {
        observer = drawnFeature.geometry.coordinates as [number, number];
      } else if (place) {
        observer = [place.longitude, place.latitude];
      } else {
        const [w, s, e, n] = analysisBbox;
        observer = [(w + e) / 2, (s + n) / 2];
      }
      if (line && line.coordinates.length >= 2) {
        const first = line.coordinates[0];
        const last = line.coordinates[line.coordinates.length - 1];
        observer = [first[0], first[1]];
        target = [last[0], last[1]];
      }
      const result = await terrainService.compute({
        product,
        bbox: [...analysisBbox],
        aoi: aoiGeoJson?.geometry ?? null,
        size: 256,
        observer,
        target,
        profile_line: line ?? undefined,
        scene_id: product === 'dem' ? focusScene?.id : undefined,
      });
      setLastLegend((result.legend as LegendInfo | null) ?? null);
      setLastMessage(result.message || result.formula || product);

      const isDem = product === 'dem';
      const drapeUrl =
        isDem && result.drape_base64
          ? terrainService.toDataUrl(result.drape_base64)
          : null;
      if (result.overlay_base64 || result.geojson || (isDem && result.dem_grid)) {
        upsertOverlay({
          id: isDem ? 'terrain-dem-base' : `terrain-${product}`,
          kind: 'terrain',
          url: result.overlay_base64
            ? terrainService.toDataUrl(result.overlay_base64)
            : '',
          bounds: result.bounds as [number, number, number, number],
          geojson: (result.geojson as GeoJSON.GeoJsonObject | null) ?? null,
          // Visible elev color base under the Eye-On satellite
          opacity: isDem ? 0.7 : layerOpacity,
          label: isDem ? 'DEM base (under imagery)' : product.replaceAll('_', ' '),
          visible: true,
          demGrid: isDem ? result.dem_grid ?? null : null,
          demStats: isDem ? result.dem_stats ?? null : null,
          exaggeration: isDem ? 1.2 : undefined,
          terrainRole: isDem ? 'base' : 'analysis',
          textureUrl: drapeUrl,
        });
      }

      if (isDem) {
        useWorkflowStore.getState().setMapChrome({
          view3d: true,
          terrainRelief: true,
        });
        const state = useWorkflowStore.getState();
        for (const o of state.overlays) {
          if (o.kind === 'scene' && o.visible !== false) {
            // Keep satellite clearly on top of DEM base
            state.upsertOverlay({ ...o, opacity: Math.max(o.opacity, 0.85) });
          }
        }
        const relief = result.dem_stats?.relief_m;
        setLastMessage(
          [
            result.message || 'DEM base under satellite',
            relief != null ? `relief ${Math.round(relief)} m` : null,
            'image overlaid on elevation',
          ]
            .filter(Boolean)
            .join(' · '),
        );
      }
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setToolLoading(false);
      setToolStatus(null);
    }
  };

  const runDetection = async (task: string) => {
    const opticalShip =
      task === 'ship_detection' || task === 'ship_detection_optical';
    if (opticalShip) {
      const blocked = opticalShipBlockReason(
        Boolean(focusScene),
        focusScene?.collection ?? catalogFilters.satelliteId,
      );
      if (blocked) {
        setError(blocked);
        return;
      }
    } else if (!focusScene && !analysisBbox) {
      setError('Show a satellite scene first');
      return;
    }
    setToolLoading(true);
    setToolStatus(
      opticalShip
        ? 'Ship Detection · NIR band · ignoring water & cloud…'
        : `Detection: ${task.replaceAll('_', ' ')}…`,
    );
    setError(null);
    try {
      const result = await detectionService.run({
        task,
        bbox: [...analysisBbox],
        scene_id: focusScene?.id,
        aoi: aoiGeoJson?.geometry ?? null,
        confidence_min: opticalShip ? 0.22 : 0.35,
      });
      setLastLegend((result.legend as LegendInfo | null) ?? null);
      setLastMessage(
        result.formula
          ? `${result.message} · ${result.formula}`
          : result.message,
      );
      useWorkflowStore.getState().setMapChrome({
        compass: true,
        scaleBar: true,
        coordinates: true,
        grid: true,
      });
      upsertOverlay({
        id: `detection-${task}`,
        kind: 'detection',
        url: result.overlay_base64
          ? detectionService.toDataUrl(result.overlay_base64)
          : '',
        bounds: result.bounds as [number, number, number, number],
        geojson: result.geojson,
        opacity: layerOpacity,
        label: task.replaceAll('_', ' '),
        visible: true,
      });
      if (opticalShip && result.shapefile_ready) {
        const nFeat = result.geojson?.features?.length ?? 0;
        if (nFeat > 0) {
          try {
            await detectionService.downloadShapefile(
              result.geojson,
              `ship_detection_${(focusScene?.id || 'scene').slice(0, 40)}`,
            );
            setLastMessage(
              (result.message || 'Ship Detection complete') +
                ' · shapefile (points + polygons) downloaded',
            );
          } catch {
            setLastMessage(
              (result.message || 'Ship Detection complete') +
                ' · map vectors ready (shapefile download failed — retry export)',
            );
          }
        } else {
          setLastMessage(
            (result.message || 'No ships found') +
              ' · try a coastal / harbor scene with the eye on (no shapefile when empty)',
          );
        }
      }
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setToolLoading(false);
      setToolStatus(null);
    }
  };

  const runGis = async (op: string) => {
    if (op === 'buffer') {
      setExpandedToolbox('gis');
      setToolStatus('Set buffer distance below, then Apply');
      return;
    }
    if (!drawnFeature) {
      setError('Draw a point, line, or polygon first');
      return;
    }
    setToolLoading(true);
    setToolStatus(`GIS ${op}…`);
    setError(null);
    try {
      const geoms: GeoJSON.Geometry[] = [drawnFeature.geometry];
      if (aoiGeoJson?.geometry && aoiGeoJson.geometry !== drawnFeature.geometry) {
        geoms.push(aoiGeoJson.geometry);
      }
      // For single-geometry ops that need two inputs, synthesize a second from bbox corners
      if (geoms.length < 2 && ['intersect', 'union', 'clip', 'spatial_join'].includes(op)) {
        const [w, s, e, n] = analysisBbox;
        geoms.push({
          type: 'Polygon',
          coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
        });
      }
      const result = await gisService.spatial(op, geoms, 500);
      setLastMessage(result.message || `${op} complete (${result.count ?? 0})`);
      const gj =
        result.geojson ||
        (result.geometry
          ? {
              type: 'FeatureCollection' as const,
              features: [
                {
                  type: 'Feature' as const,
                  properties: { operation: op },
                  geometry: result.geometry,
                },
              ],
            }
          : null);
      if (gj && result.bounds) {
        upsertOverlay({
          id: `gis-${op}`,
          kind: 'buffer',
          url: '',
          bounds: result.bounds as [number, number, number, number],
          geojson: gj,
          opacity: layerOpacity,
          label: `GIS ${op}`,
          visible: true,
        });
      }
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setToolLoading(false);
      setToolStatus(null);
    }
  };

  const onApplyBuffer = async (distanceMeters: number) => {
    if (!drawnFeature) return;
    setBufferLoading(true);
    setError(null);
    try {
      const result = await gisService.buffer(drawnFeature.geometry, distanceMeters);
      setLastBufferDistance(result.distance_meters);
      setLastBufferArea(result.area_sq_meters ?? null);
      const bufferFeature: GeoJSON.Feature = {
        type: 'Feature',
        properties: { distance_meters: result.distance_meters },
        geometry: result.geometry as GeoJSON.Geometry,
      };
      upsertOverlay({
        id: 'buffer-layer',
        kind: 'buffer',
        url: '',
        bounds: result.bounds as [number, number, number, number],
        geojson: bufferFeature,
        opacity: layerOpacity,
        label: `Buffer ${distanceMeters} m`,
        visible: true,
      });
      if (result.geometry.type === 'Polygon') {
        setBufferGeoJson(result.geometry as GeoJSON.Polygon);
      } else {
        setBufferGeoJson(null);
      }
      setLastMessage(`Buffer ${distanceMeters} m applied`);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBufferLoading(false);
    }
  };

  const applyProcessFilter = (op: string) => {
    if (op === 'true_color') {
      // Never leave CSS brightness/contrast on the map — it neon-blows True Color
      setProcessFilter({ brightness: 1, contrast: 1, gamma: 1 });
      setStretchParams((s) => ({ ...s, brightness: 1.0, contrast: 1.0, gamma: 1.2 }));
      void runComposite('true_color');
      return;
    }
    if (op === 'false_color') {
      // Cycle USGS/ESA professional false-color recipes on repeat clicks
      const fccCycle: CompositePreset[] = [
        'false_color_infrared',
        'false_color_agriculture',
        'false_color_urban',
        'swir_composite',
        'land_water',
        'vegetation_health',
        'burn_severity',
        'geology',
        'atmospheric_penetration',
      ];
      const cur = (compositeResult?.preset || 'false_color_infrared') as CompositePreset;
      const idx = fccCycle.indexOf(cur);
      const next = fccCycle[(idx + 1) % fccCycle.length];
      void runComposite(next);
      return;
    }
    if (op === 'unsupervised_classify') {
      void runClassification();
      return;
    }
    if (op === 'histogram') {
      void runStretch();
      return;
    }
    if (op === 'brightness' || op === 'contrast' || op === 'gamma') {
      const next = { ...stretchParams };
      if (op === 'brightness') next.brightness = Math.min(1.8, next.brightness + 0.1);
      if (op === 'contrast') next.contrast = Math.min(2.0, next.contrast + 0.1);
      if (op === 'gamma') next.gamma = Math.min(2.2, next.gamma + 0.1);
      setStretchParams(next);
      setProcessFilter({
        brightness: next.brightness,
        contrast: next.contrast,
        gamma: next.gamma,
      });
      void runStretch(next);
      return;
    }
    if (op === 'sharpen' || op === 'denoise') {
      void runStretch({
        ...stretchParams,
        contrast: Math.min(2, stretchParams.contrast + 0.15),
        brightness: Math.min(1.5, stretchParams.brightness + 0.05),
      });
      setLastMessage(`${op} via contrast/edge-enhanced stretch`);
      return;
    }
    if (op === 'mosaic') {
      setLastMessage('Mosaic: all visible scene layers shown (professional multi-scene stack)');
      return;
    }
    if (op === 'reproject' || op === 'resample') {
      setLastMessage(
        `${op}: display CRS EPSG:3857 · interactive grid ≤640px (slow-link professional preview)`,
      );
    }
  };

  const recolorClassification = async (
    styles: import('../services/classificationService').ClassStyle[],
  ) => {
    if (!classificationResult?.class_map_base64 || !focusScene) {
      setError('Run classification first, then change colors');
      return;
    }
    try {
      // Instant local recolor for the map overlay
      const dataUrl = await classificationService.recolorLocal(
        classificationResult.class_map_base64,
        styles.map((s) => ({
          class_id: s.class_id ?? 0,
          color: s.color,
        })),
      );
      const overlayB64 = dataUrl.includes(',') ? dataUrl.split(',')[1] : dataUrl;
      const nextClasses = classificationResult.classes.map((c) => {
        const style = styles.find(
          (s) => s.class_id === c.class_id || s.name === c.name,
        );
        return style
          ? { ...c, color: style.color, label: style.label || c.label }
          : c;
      });
      setClassificationResult({
        ...classificationResult,
        overlay_base64: overlayB64,
        classes: nextClasses,
        message: `Recolored ${nextClasses.length} classes (classification unchanged)`,
      });
      upsertOverlay({
        id: `classify-${focusScene.id}`,
        kind: 'classify',
        sceneId: focusScene.id,
        url: dataUrl.startsWith('data:')
          ? dataUrl
          : classificationService.toDataUrl(overlayB64),
        bounds: classificationResult.bounds as [number, number, number, number],
        opacity: 1,
        label: `LULC ${nextClasses.length}-class (opaque)`,
        visible: true,
      });
      setLastMessage(`Recolored ${nextClasses.length} classes`);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const runClassification = async (opts?: {
    n_classes?: import('../services/classificationService').ClassCount;
    class_styles?: import('../services/classificationService').ClassStyle[];
  }) => {
    if (!focusScene) {
      setError('Show a satellite scene first (eye icon)');
      return;
    }
    {
      const blocked = opticalProcessingBlockReason(focusScene.collection);
      if (blocked) {
        setError(blocked);
        return;
      }
    }
    const nClasses = opts?.n_classes ?? 6;
    setToolLoading(true);
    setActiveToolId('unsupervised_classify');
    setToolStatus(`Unsupervised classification (${nClasses} classes)…`);
    setError(null);
    try {
      const sceneOverlay = overlays.find(
        (o) => o.kind === 'scene' && o.sceneId === focusScene.id,
      );
      // Always classify over the same geographic extent as the eye-loaded scene
      // (not the place pin / small AOI), so the overlay covers the complete image.
      const bounds = sceneOverlay?.bounds ?? sceneBounds(focusScene, place);

      const result = await classificationService.classify({
        scene_id: focusScene.id,
        bbox: [...bounds],
        size: 512,
        n_classes: nClasses,
        class_styles: opts?.class_styles,
      });
      setClassificationResult(result);
      setLastLegend(result.legend);
      setLastMessage(result.message);
      upsertOverlay({
        id: `classify-${focusScene.id}`,
        kind: 'classify',
        sceneId: focusScene.id,
        url: classificationService.toDataUrl(result.overlay_base64),
        // Prefer backend bounds, but never shrink below the original scene extent.
        bounds: (result.bounds as [number, number, number, number]) ?? bounds,
        footprint: sceneOverlay?.footprint ?? null,
        opacity: 1,
        label: `LULC ${nClasses}-class (opaque)`,
        visible: true,
      });
      useWorkflowStore.getState().setExpandedToolbox('image');
      useWorkflowStore.getState().setToolboxOpen(true);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setToolLoading(false);
      setToolStatus(null);
    }
  };

  const runComposite = async (preset: CompositePreset) => {
    if (!focusScene) {
      setError('Show a satellite scene first (eye icon)');
      return;
    }
    {
      const blocked = opticalProcessingBlockReason(focusScene.collection);
      if (blocked) {
        setError(blocked);
        return;
      }
    }
    setToolLoading(true);
    setActiveToolId(`composite-${preset}`);
    setToolStatus(`Rendering ${preset.replaceAll('_', ' ')}…`);
    setError(null);
    try {
      const sceneOverlay = overlays.find(
        (o) => o.kind === 'scene' && o.sceneId === focusScene.id,
      );
      // Always process over the same geographic extent as the original scene layer.
      const bounds = sceneOverlay?.bounds ?? sceneBounds(focusScene, place);
      const stretch =
        preset === 'true_color'
          ? { p_low: 2, p_high: 98, gamma: 1.0, brightness: 1.0, contrast: 1.0 }
          : stretchParams;
      const result = await compositeService.render({
        preset,
        scene_id: focusScene.id,
        collection: focusScene.collection,
        bbox: [...bounds],
        size: 512,
        ...stretch,
      });
      setCompositeResult(result);
      setLastLegend((result.legend as LegendInfo | null) ?? null);
      setLastMessage(
        `${result.label} · ${result.formula} · download GeoTIFF from Image Processing exports`,
      );
      upsertOverlay({
        id: `composite-${preset}`,
        kind: 'index',
        sceneId: focusScene.id,
        url: compositeService.toDataUrl(result.overlay_base64),
        // Prefer backend bounds, but never shrink below the original scene extent.
        bounds: (result.bounds as [number, number, number, number]) ?? bounds,
        footprint: sceneOverlay?.footprint ?? null,
        // RGB composites should be fully opaque for natural color
        opacity: 1,
        label: result.label,
        visible: true,
      });
      useWorkflowStore.getState().setExpandedToolbox('image');
      useWorkflowStore.getState().setToolboxOpen(true);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setToolLoading(false);
      setToolStatus(null);
    }
  };

  const runStretch = async (params = stretchParams) => {
    if (!focusScene) {
      setError('Show a satellite scene first (eye icon)');
      return;
    }
    {
      const blocked = opticalProcessingBlockReason(focusScene.collection);
      if (blocked) {
        setError(blocked);
        return;
      }
    }
    setToolLoading(true);
    setActiveToolId('histogram');
    setToolStatus('Applying histogram stretch…');
    setError(null);
    try {
      const sceneOverlay = overlays.find(
        (o) => o.kind === 'scene' && o.sceneId === focusScene.id,
      );
      const bounds = sceneOverlay?.bounds ?? sceneBounds(focusScene, place);
      const result = await compositeService.stretch({
        scene_id: focusScene.id,
        bbox: [...bounds],
        size: 512,
        ...params,
      });
      setStretchResult(result);
      setLastMessage(result.message);
      upsertOverlay({
        id: 'stretch-overlay',
        kind: 'index',
        sceneId: focusScene.id,
        url: compositeService.toDataUrl(result.overlay_base64),
        bounds: (result.bounds as [number, number, number, number]) ?? bounds,
        footprint: sceneOverlay?.footprint ?? null,
        opacity: layerOpacity,
        label: `Stretch ${params.p_low}-${params.p_high}%`,
        visible: true,
      });
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setToolLoading(false);
      setToolStatus(null);
    }
  };

  const exportActiveOverlayPng = () => {
    const last = [...overlays].reverse().find(
      (o) =>
        (o.kind === 'classify' ||
          o.kind === 'index' ||
          o.kind === 'change' ||
          o.kind === 'terrain' ||
          o.kind === 'detection') &&
        o.url,
    );
    if (!last?.url) {
      setError('No processed overlay to export — run an index, composite, or stretch first');
      return;
    }
    if (
      (last.kind === 'classify' || last.id.startsWith('classify-')) &&
      classificationResult
    ) {
      void classificationService
        .downloadDecoratedPng(classificationResult, focusScene?.id || 'scene')
        .catch((err) => setError(getErrorMessage(err)));
      return;
    }
    const a = document.createElement('a');
    a.href = last.url;
    a.download = `${last.label.replace(/\W+/g, '_')}.png`;
    a.click();
  };

  const exportActiveOverlayGeotiff = async () => {
    const last = [...overlays].reverse().find(
      (o) =>
        (o.kind === 'classify' ||
          o.kind === 'index' ||
          o.kind === 'change' ||
          o.kind === 'terrain' ||
          o.kind === 'detection' ||
          o.kind === 'scene') &&
        (o.url || o.demGrid?.length),
    );
    if (!last) {
      setError('No processed overlay to export as GeoTIFF — run a procedure first');
      return;
    }
    await downloadLayerGeotiff(last);
  };

  const downloadLayerGeotiff = async (layer: (typeof overlays)[number]) => {
    setGeotiffBusy(true);
    setGeotiffLayerId(layer.id);
    setError(null);
    setToolStatus(`Exporting ${layer.label} GeoTIFF…`);
    try {
      const isClassify =
        layer.kind === 'classify' ||
        layer.id.startsWith('classify-') ||
        /^LULC\b/i.test(layer.label);
      if (isClassify && classificationResult) {
        const sceneId =
          layer.sceneId || focusScene?.id || classificationResult.metadata?.scene_id;
        if (!sceneId || typeof sceneId !== 'string') {
          throw new Error('Missing scene id for classification GeoTIFF');
        }
        // Use current overlay pixels (includes recolor) + class areas for legend
        const overlayB64 = layer.url
          ? await compositeService.overlayUrlToBase64(layer.url)
          : classificationResult.overlay_base64;
        await classificationService.downloadGeotiff(
          {
            ...classificationResult,
            overlay_base64: overlayB64,
            bounds: [...layer.bounds],
          },
          sceneId,
        );
        setLastMessage(
          `Downloaded GeoTIFF · LULC map sheet with legend (${Math.round(classificationResult.total_area_km2)} km²)`,
        );
        return;
      }

      const filename = `${layer.label.replace(/\W+/g, '_') || layer.kind}.tif`;
      if (layer.demGrid?.length) {
        await compositeService.downloadGeotiff({
          bounds: [...layer.bounds],
          filename,
          dem_grid: layer.demGrid,
        });
      } else if (layer.url) {
        const overlay_base64 = await compositeService.overlayUrlToBase64(layer.url);
        await compositeService.downloadGeotiff({
          bounds: [...layer.bounds],
          filename,
          overlay_base64,
          procedure: 'overlay',
        });
      } else {
        throw new Error('Layer has no raster to export');
      }
      setLastMessage(`Downloaded GeoTIFF · ${layer.label}`);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setGeotiffBusy(false);
      setGeotiffLayerId(null);
      setToolStatus(null);
    }
  };

  const deactivateTool = useCallback(
    (tool: ToolboxTool) => {
      setActiveToolId(null);
      setToolStatus(null);
      setLastMessage(`${tool.label} turned off`);
      const { action } = tool;

      if (action.type === 'measure' || action.type === 'map') {
        setMapTool('navigate');
        setMeasureLabel(null);
      }

      if (action.type === 'toggle') {
        const key = action.key as keyof typeof mapChrome;
        if (key in mapChrome && mapChrome[key]) {
          toggleMapChrome(key);
        }
        if (action.key === 'view2d') {
          useWorkflowStore.getState().setMapChrome({ view3d: false, rotate: false });
        }
      }

      if (action.type === 'index') {
        removeOverlaysByKind('index');
        setIndexResult(null);
        setSelectedIndex(null);
        setLastLegend(null);
      }
      if (action.type === 'change') {
        removeOverlaysByKind('change');
        setChangeResult(null);
        setLastLegend(null);
      }
      if (action.type === 'terrain') {
        const wasDem = action.product === 'dem';
        removeOverlaysByKind('terrain');
        setLastLegend(null);
        if (wasDem) {
          useWorkflowStore.getState().setMapChrome({
            view3d: false,
            terrainRelief: false,
          });
          const state = useWorkflowStore.getState();
          for (const o of state.overlays) {
            if (o.kind === 'scene') {
              state.upsertOverlay({ ...o, opacity: 1 });
            }
          }
        }
      }
      if (action.type === 'detection') {
        removeOverlaysByKind('detection');
        setLastLegend(null);
      }
      if (action.type === 'gis') {
        if (action.op === 'buffer') {
          setBufferGeoJson(null);
          removeOverlaysByKind('buffer');
          setLastBufferDistance(null);
          setLastBufferArea(null);
        } else {
          removeOverlay(`gis-${action.op}`);
        }
      }
      if (action.type === 'process') {
        setProcessFilter({ brightness: 1, contrast: 1, gamma: 1 });
      }
    },
    [
      mapChrome,
      removeOverlay,
      removeOverlaysByKind,
      setBufferGeoJson,
      setChangeResult,
      setIndexResult,
      setMapTool,
      setMeasureLabel,
      setSelectedIndex,
      toggleMapChrome,
    ],
  );

  const onTool = async (tool: ToolboxTool) => {
    if (!catalogFilters.satelliteId) {
      setError('Select a satellite first to activate toolbox options');
      setToolStatus('Select a satellite to use tools');
      return;
    }
    // All 148 tools active — optical detectors/change use professional spectral recipes.
    // (Former high-res-only gate removed.)

    // Clicking the active tool again turns it off
    if (activeToolId === tool.id) {
      deactivateTool(tool);
      return;
    }

    setActiveToolId(tool.id);
    const { action } = tool;

    if (action.type === 'map') {
      if (action.mode === 'navigate') setMapTool('navigate');
      else if (action.mode === 'zoom-in' || action.mode === 'zoom-out' || action.mode === 'fullscreen') {
        setMapCommand({ id: Date.now(), type: action.mode === 'fullscreen' ? 'fullscreen' : action.mode });
        // One-shot commands should not stay selected
        setActiveToolId(null);
      }
      setToolStatus(`Map: ${tool.label}`);
      return;
    }

    if (action.type === 'toggle') {
      if (action.key === 'view2d') {
        useWorkflowStore.getState().setMapChrome({ view3d: false, rotate: false });
        setToolStatus('2D view');
        return;
      }
      if (action.key === 'fullscreen') {
        setMapCommand({ id: Date.now(), type: 'fullscreen' });
        setActiveToolId(null);
        return;
      }
      const key = action.key as keyof typeof mapChrome;
      if (key in mapChrome) {
        const turningOn = !mapChrome[key];
        toggleMapChrome(key);
        if (!turningOn) {
          setActiveToolId(null);
          setToolStatus(`${tool.label}: OFF`);
          return;
        }
        if (key === 'bookmarks') {
          try {
            const list = await bookmarkService.list();
            setLastMessage(
              list.length
                ? `Bookmarks: ${list.map((b) => b.name).join(', ')}`
                : 'No bookmarks yet — pan to a place and save from Place step',
            );
          } catch {
            setLastMessage('Bookmarks panel toggled');
          }
        }
        setToolStatus(`${tool.label}: ON`);
      }
      return;
    }

    if (action.type === 'measure') {
      setMapTool(action.mode as MapTool);
      setToolStatus(`Measure: ${tool.label} — draw on the map`);
      return;
    }

    if (action.type === 'index') {
      await runIndex(action.index as IndexName);
      return;
    }

    if (action.type === 'terrain') {
      await runTerrain(action.product as TerrainProduct);
      return;
    }

    if (action.type === 'detection') {
      await runDetection(action.task);
      return;
    }

    if (action.type === 'change') {
      await runChange(action.mode);
      return;
    }

    if (action.type === 'gis') {
      await runGis(action.op);
      return;
    }

    if (action.type === 'layer') {
      const last = overlays[overlays.length - 1];
      if (action.op === 'add') {
        setToolStatus('Add layer: toggle a scene eye in the catalog');
      } else if (action.op === 'remove' && last) {
        removeOverlay(last.id);
        setToolStatus(`Removed ${last.label}`);
        setActiveToolId(null);
      } else if (action.op === 'duplicate' && last) {
        duplicateOverlay(last.id);
        setToolStatus(`Duplicated ${last.label}`);
        setActiveToolId(null);
      } else if (action.op === 'opacity' || action.op === 'transparency') {
        setExpandedToolbox('layers');
        setToolStatus('Adjust opacity in Layer Manager');
        setActiveToolId(null);
      } else if (action.op === 'order') {
        setExpandedToolbox('layers');
        setToolStatus('Use Up/Down in Layer Manager');
        setActiveToolId(null);
      } else if (action.op === 'rename') {
        setExpandedToolbox('layers');
        setToolStatus('Double-click a layer name to rename');
        setActiveToolId(null);
      } else if (action.op === 'styles' || action.op === 'labels' || action.op === 'blend') {
        setLastMessage(`${action.op}: use detection/index overlays for styled results`);
        setActiveToolId(null);
      }
      return;
    }

    if (action.type === 'process') {
      applyProcessFilter(action.op);
    }
  };

  const onExportJpeg = async () => {
    const host = mapHostRef.current;
    if (!host) return;
    const mapElement =
      (host.querySelector('.leaflet-container') as HTMLElement | null) || host;
    setExporting(true);
    try {
      const legend =
        lastLegend || changeResult?.legend || indexResult?.legend || null;
      await exportMapJpeg({
        mapElement,
        title: 'SAT EYE Map Export',
        placeName: place?.name,
        legend,
        filename: `sateye-${(place?.name || 'map').replace(/\W+/g, '_').slice(0, 40)}.jpg`,
      });
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setExporting(false);
    }
  };

  const legend: LegendInfo | null =
    lastLegend || changeResult?.legend || indexResult?.legend || null;

  const filterStyle =
    processFilter.brightness !== 1 || processFilter.contrast !== 1
      ? {
          filter: `brightness(${processFilter.brightness}) contrast(${processFilter.contrast})`,
        }
      : undefined;

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--line)] bg-white px-3 py-2 sm:px-4">
        <div className="min-w-0">
          <div className="font-display text-sm font-semibold tracking-wide sm:text-base">
            SAT EYE Pakistan
          </div>
          <div className="text-[10px] uppercase tracking-[0.16em] text-[var(--muted)]">
            Eye In Sky
          </div>
        </div>

        <div className="flex items-center gap-2">
          {isAdmin && (
            <>
              <button
                type="button"
                className="ev-btn inline-flex items-center gap-1.5 rounded-lg border border-[var(--accent)] bg-[var(--accent-soft)] px-2.5 py-2 text-xs font-semibold text-[var(--accent)] hover:bg-[var(--accent)] hover:text-white"
                onClick={() => {
                  setAdminTab('clients');
                  setAdminOpen(true);
                }}
                title="Admin only: approve clients, tools, satellites"
              >
                <Shield className="h-4 w-4" />
                <span>Admin · Clients</span>
              </button>
              <button
                type="button"
                className="ev-btn inline-flex items-center gap-1.5 rounded-lg border border-[var(--line)] px-2.5 py-2 text-xs font-semibold text-[var(--ink)] hover:bg-[var(--accent-soft)]"
                onClick={() => {
                  setAdminTab('satellites');
                  setAdminOpen(true);
                }}
                title="Admin only: add satellite catalog APIs"
              >
                <span>Add Satellite API</span>
              </button>
            </>
          )}
          <button
            type="button"
            className={`ev-btn inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold ${
              toolboxOpen
                ? 'bg-[var(--accent)] text-white'
                : 'border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent-soft)]'
            }`}
            onClick={() => setToolboxOpen(!toolboxOpen)}
          >
            <Wrench className="h-4 w-4" />
            Toolboxes ({toolCount})
          </button>
          <span className="hidden max-w-[10rem] truncate text-xs text-[var(--muted)] sm:inline">
            {user?.full_name}
          </span>
          <button type="button" className="ev-btn-ghost p-2" onClick={logout} title="Sign out">
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </header>

      {adminOpen && isAdmin && (
        <AdminPanel
          key={adminTab}
          initialTab={adminTab}
          onClose={() => {
            setAdminOpen(false);
            setSatelliteRefreshKey((n) => n + 1);
          }}
        />
      )}

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[min(21rem,100%)] shrink-0 flex-col gap-3 overflow-y-auto border-r border-[var(--line)] bg-white p-3 sm:p-4">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </div>
          )}

          {step === 'place' && (
            <PlaceStep
              onSelect={loadScenesForPlace}
              busy={loadingScenes}
              filters={catalogFilters}
              onFiltersChange={setCatalogFilters}
              isAdmin={isAdmin}
              satelliteRefreshKey={satelliteRefreshKey}
              onOpenSatelliteAdmin={
                isAdmin
                  ? () => {
                      setAdminTab('satellites');
                      setAdminOpen(true);
                    }
                  : undefined
              }
            />
          )}

          {step === 'browse' && place && (
            <ScenesStep
              placeName={place.name}
              scenes={scenes}
              visibleSceneIds={visibleSceneIds}
              focusSceneId={focusSceneId}
              loading={loadingScenes}
              loadingOverlayIds={loadingOverlayIds}
              satelliteLabel={catalogFilters.satelliteLabel}
              dateFrom={catalogFilters.startDate}
              dateTo={catalogFilters.endDate}
              onToggleEye={onToggleEye}
              onFocus={(scene) => setFocusSceneId(scene.id)}
              onBack={backToPlace}
            />
          )}
        </aside>

        <section
          ref={mapHostRef}
          className="relative min-h-[40vh] min-w-0 flex-1 lg:min-h-0"
          id="ev-map-host"
          style={filterStyle}
        >
          <LightMap
            place={place}
            overlays={overlays}
            mapTool={mapTool}
            aoiGeoJson={aoiGeoJson}
            drawnFeature={drawnFeature}
            bufferGeoJson={bufferGeoJson}
            enablePlaceClick={step === 'place'}
            showGrid={mapChrome.grid !== false}
            mapChrome={mapChrome}
            mapCommand={mapCommand}
            onPlaceClick={onPlaceClick}
            onAoiComplete={(feature) => {
              setAoiGeoJson(feature);
              if (feature.geometry.type === 'Polygon') {
                onDrawnFeature({
                  type: 'Polygon',
                  geometry: feature.geometry,
                  label: 'AOI',
                });
              }
              setMapTool('navigate');
            }}
            onDrawnFeature={onDrawnFeature}
            onMeasure={setMeasureLabel}
          />
          <MapToolbar
            tool={mapTool}
            measureLabel={measureLabel}
            layerOpacity={layerOpacity}
            onTool={(t) => {
              // Clicking the active map tool again returns to Pan
              if (t === mapTool && t !== 'navigate') {
                setMapTool('navigate');
                setMeasureLabel(null);
                setActiveToolId(null);
                return;
              }
              setMapTool(t);
              if (t === 'navigate') setMeasureLabel(null);
            }}
            onOpacity={setLayerOpacity}
            onClearAoi={() => clearDrawn()}
            onExportJpeg={onExportJpeg}
            hasAoi={Boolean(aoiGeoJson || drawnFeature || bufferGeoJson)}
            exporting={exporting}
          />
          <MapLegend legend={legend} />
          {mapChrome.splitView && hasVisibleScene && (
            <div className="pointer-events-none absolute inset-y-0 left-1/2 z-[400] w-px bg-[var(--accent)]/70" />
          )}
          {mapChrome.timeSlider && (
            <div className="pointer-events-auto absolute inset-x-8 bottom-24 z-[1000] rounded-xl border border-[var(--line)] bg-white/95 px-3 py-2 shadow">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-[var(--muted)]">
                Time slider · {scenes.length} scenes
              </div>
              <input
                type="range"
                min={0}
                max={Math.max(0, scenes.length - 1)}
                defaultValue={Math.max(0, scenes.findIndex((s) => s.id === focusSceneId))}
                className="w-full accent-[var(--accent)]"
                onChange={(e) => {
                  const sc = scenes[Number(e.target.value)];
                  if (sc) setFocusSceneId(sc.id);
                }}
              />
            </div>
          )}
          {step === 'place' && (
            <div className="pointer-events-none absolute bottom-14 left-1/2 z-[500] max-w-[90%] -translate-x-1/2 rounded-full bg-white/95 px-3 py-1.5 text-center text-xs text-[var(--muted)] shadow">
              Search Lahore, click the map, or draw an AOI — then use eyes to show images
            </div>
          )}
        </section>

        {toolboxOpen ? (
          <div className="flex w-[min(24rem,100%)] shrink-0 flex-col overflow-hidden">
            <ToolboxPanel
              expanded={(expandedToolbox as ToolboxId | null) ?? 'image'}
              activeToolId={activeToolId}
              loading={toolLoading}
              status={toolStatus}
              overlays={overlays}
              layerOpacity={layerOpacity}
              hasScene={hasVisibleScene}
              sceneCollection={
                focusScene?.collection ?? catalogFilters.satelliteId ?? null
              }
              hasDrawn={Boolean(drawnFeature)}
              drawnType={drawnFeature?.type ?? null}
              bufferLoading={bufferLoading}
              lastBufferDistance={lastBufferDistance}
              lastBufferArea={lastBufferArea}
              lastLegend={lastLegend}
              lastMessage={lastMessage}
              mapChrome={mapChrome}
              allowedTools={allowedTools}
              toolsEnabled={satelliteActive}
              onExpand={(id) => setExpandedToolbox(id)}
              onTool={onTool}
              onClose={() => setToolboxOpen(false)}
              onOpacity={setLayerOpacity}
              onToggleOverlay={(id) => {
                const layer = overlays.find((o) => o.id === id);
                if (layer) setOverlayVisible(id, layer.visible === false);
              }}
              onRemoveOverlay={removeOverlay}
              onMoveOverlay={moveOverlay}
              onReorderOverlays={reorderOverlaysDisplay}
              onPatchOverlay={patchOverlay}
              onRenameOverlay={renameOverlay}
              onApplyBuffer={onApplyBuffer}
              onClearBuffer={() => {
                setBufferGeoJson(null);
                removeOverlaysByKind('buffer');
                setLastBufferDistance(null);
                setLastBufferArea(null);
              }}
              indexResult={indexResult}
              compositeResult={compositeResult}
              stretchResult={stretchResult}
              classificationResult={classificationResult}
              stretchParams={stretchParams}
              colormap={selectedColormap}
              onComposite={(preset) => void runComposite(preset)}
              onIndexTool={(index) => void runIndex(index)}
              onClassify={(opts) => void runClassification(opts)}
              onRecolorClassify={(styles) => void recolorClassification(styles)}
              onColormapChange={(cmap) => {
                setSelectedColormap(cmap);
                if (indexResult?.index) {
                  void runIndex(indexResult.index as IndexName, cmap);
                }
              }}
              onStretch={() => void runStretch()}
              onStretchParams={(patch) =>
                setStretchParams((s) => ({ ...s, ...patch }))
              }
              onEnhance={(op) => applyProcessFilter(op)}
              onExportClassifyPng={() => {
                if (!classificationResult?.overlay_base64 || !focusScene) {
                  setError('Run Unsupervised Classify first');
                  return;
                }
                void classificationService
                  .downloadDecoratedPng(classificationResult, focusScene.id)
                  .catch((err) => setError(getErrorMessage(err)));
              }}
              onExportClassifyCsv={() => {
                if (!classificationResult || !focusScene) {
                  setError('Run Unsupervised Classify first');
                  return;
                }
                classificationService.downloadCsvText(
                  classificationService.buildResultsCsv(classificationResult),
                  `lulc4_${focusScene.id}_areas.csv`,
                );
              }}
              onExportClassifyGeotiff={() => {
                if (!classificationResult || !focusScene) {
                  setError('Run Unsupervised Classify first');
                  return;
                }
                setGeotiffBusy(true);
                void classificationService
                  .downloadGeotiff(classificationResult, focusScene.id)
                  .then(() =>
                    setLastMessage(
                      `Downloaded GeoTIFF · LULC ${classificationResult.classes.length}-class (${Math.round(classificationResult.total_area_km2)} km²)`,
                    ),
                  )
                  .catch((err) => setError(getErrorMessage(err)))
                  .finally(() => setGeotiffBusy(false));
              }}
              onExportIndexPng={() => {
                if (!indexResult || !focusScene) {
                  setError('Compute an index first');
                  return;
                }
                if (indexResult.overlay_base64) {
                  void compositeService.downloadPngFromBase64(
                    indexResult.overlay_base64,
                    `${indexResult.index}_${focusScene.id}.png`,
                  );
                } else {
                  void compositeService.downloadIndexPng(
                    indexResult.index,
                    focusScene.id,
                    analysisBbox,
                  );
                }
              }}
              onExportIndexCsv={() => {
                if (!indexResult || !focusScene) {
                  setError('Compute an index first');
                  return;
                }
                void compositeService.downloadIndexCsv(indexResult.index, focusScene.id);
              }}
              onExportCompositePng={() => {
                if (compositeResult?.overlay_base64) {
                  void compositeService.downloadPngFromBase64(
                    compositeResult.overlay_base64,
                    `${compositeResult.preset}.png`,
                  );
                } else {
                  void compositeService.downloadCompositePng(
                    compositeResult?.preset || 'false_color_infrared',
                    focusScene?.id,
                    analysisBbox,
                  );
                }
              }}
              onExportStretchPng={() => {
                if (!stretchResult?.overlay_base64) {
                  setError('Apply histogram stretch first');
                  return;
                }
                void compositeService.downloadPngFromBase64(
                  stretchResult.overlay_base64,
                  `stretch_${focusScene?.id || 'aoi'}.png`,
                );
              }}
              onExportOverlayPng={exportActiveOverlayPng}
              onExportIndexGeotiff={() => {
                if (!indexResult || !focusScene) {
                  setError('Compute an index first');
                  return;
                }
                setGeotiffBusy(true);
                void compositeService
                  .downloadGeotiff({
                    bounds: (indexResult.bounds as number[]) || [...analysisBbox],
                    filename: `${indexResult.index}_${focusScene.id}.tif`,
                    overlay_base64: indexResult.overlay_base64,
                    procedure: indexResult.overlay_base64 ? 'overlay' : 'index',
                    scene_id: focusScene.id,
                    index: indexResult.index,
                    colormap: indexResult.colormap,
                  })
                  .then(() => setLastMessage(`Downloaded GeoTIFF · ${indexResult.index}`))
                  .catch((err) => setError(getErrorMessage(err)))
                  .finally(() => setGeotiffBusy(false));
              }}
              onExportCompositeGeotiff={() => {
                if (!compositeResult) {
                  setError('Render a composite (e.g. True Color) first');
                  return;
                }
                setGeotiffBusy(true);
                void compositeService
                  .downloadGeotiff({
                    bounds: [...compositeResult.bounds],
                    filename: `${compositeResult.preset}.tif`,
                    overlay_base64: compositeResult.overlay_base64,
                    procedure: compositeResult.overlay_base64 ? 'overlay' : 'composite',
                    scene_id: focusScene?.id,
                    preset: compositeResult.preset,
                  })
                  .then(() =>
                    setLastMessage(`Downloaded GeoTIFF · ${compositeResult.label}`),
                  )
                  .catch((err) => setError(getErrorMessage(err)))
                  .finally(() => setGeotiffBusy(false));
              }}
              onExportStretchGeotiff={() => {
                if (!stretchResult) {
                  setError('Apply histogram stretch first');
                  return;
                }
                setGeotiffBusy(true);
                void compositeService
                  .downloadGeotiff({
                    bounds: [...stretchResult.bounds],
                    filename: `stretch_${focusScene?.id || 'aoi'}.tif`,
                    overlay_base64: stretchResult.overlay_base64,
                    procedure: stretchResult.overlay_base64 ? 'overlay' : 'stretch',
                    scene_id: focusScene?.id,
                    p_low: stretchResult.p_low,
                    p_high: stretchResult.p_high,
                  })
                  .then(() => setLastMessage('Downloaded GeoTIFF · histogram stretch'))
                  .catch((err) => setError(getErrorMessage(err)))
                  .finally(() => setGeotiffBusy(false));
              }}
              onExportOverlayGeotiff={() => {
                void exportActiveOverlayGeotiff();
              }}
              onDownloadLayerGeotiff={(layer) => {
                void downloadLayerGeotiff(layer);
              }}
              geotiffBusy={geotiffBusy}
              geotiffLayerId={geotiffLayerId}
            />
          </div>
        ) : (
          <div className="flex w-12 shrink-0 flex-col items-center gap-1 border-l border-[var(--line)] bg-white py-2">
            <button
              type="button"
              className="rounded-lg bg-[var(--accent)] p-2 text-white"
              title="Open toolboxes"
              onClick={() => setToolboxOpen(true)}
            >
              <Wrench className="h-4 w-4" />
            </button>
            {TOOLBOXES.slice(0, 6).map((box) => (
              <button
                key={box.id}
                type="button"
                className="rounded p-1.5 text-[9px] text-[var(--muted)] hover:bg-[var(--accent-soft)]"
                title={box.title}
                onClick={() => {
                  setExpandedToolbox(box.id);
                  setToolboxOpen(true);
                }}
              >
                {box.title.split(' ')[0]}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
