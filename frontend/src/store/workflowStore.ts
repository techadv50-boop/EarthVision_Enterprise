import { create } from 'zustand';
import type { SceneSummary } from '../services/catalogService';
import type { IndexName, IndexResult, ChangeResult } from '../services/analyticsService';

export type WorkflowStep = 'place' | 'browse';
export type MapTool =
  | 'navigate'
  | 'draw-point'
  | 'measure-line'
  | 'measure-area'
  | 'aoi-rect'
  | 'aoi-poly';

export interface PlaceSelection {
  name: string;
  longitude: number;
  latitude: number;
  bbox: [number, number, number, number];
}

export interface MapOverlay {
  id: string;
  kind: 'scene' | 'index' | 'change' | 'terrain' | 'buffer' | 'detection';
  sceneId?: string;
  /** Static image URL (indices / change / terrain). Empty when using tileUrl or geojson-only. */
  url: string;
  /** XYZ tile template for sharp scene layers */
  tileUrl?: string;
  bounds: [number, number, number, number];
  /** Actual scene footprint (tilted for Landsat / S1) */
  footprint?: GeoJSON.Polygon | null;
  /** Vector overlay (contours, drainage, LOS, buffer outline) */
  geojson?: GeoJSON.GeoJsonObject | null;
  opacity: number;
  label: string;
  visible?: boolean;
  blendMode?: string;
  renderMode?: 'rgb' | 'grayscale';
  /** Elevation grid for DEM 3D mesh (row-major, north→south) */
  demGrid?: number[][] | null;
  demStats?: Record<string, number> | null;
  /** Vertical exaggeration for DEM mesh under imagery */
  exaggeration?: number;
  /** ArcScene-style orbit yaw in degrees */
  demYaw?: number;
  /** ArcScene-style pitch in degrees (higher = more top-down) */
  demPitch?: number;
  /** DEM base sits under satellite; other terrain products are analysis overlays */
  terrainRole?: 'base' | 'analysis';
  /** Satellite×hillshade texture (optional soft mix into elev colors) */
  textureUrl?: string | null;
  /** Elevation color theme for DEM mesh */
  demColormap?: string | null;
  /** 0–0.5 how much satellite texture tints the elev theme */
  demTextureMix?: number;
}

/** Drawn feature available for buffer / profile / LOS */
export interface DrawnFeature {
  type: 'Point' | 'LineString' | 'Polygon';
  geometry: GeoJSON.Geometry;
  label: string;
}

/** DEM base defaults under imagery; users may still reorder freely in Layer Manager. */
function pinDemBaseToBack(overlays: MapOverlay[]): MapOverlay[] {
  const dems = overlays.filter((o) => o.terrainRole === 'base');
  if (!dems.length) return overlays;
  const rest = overlays.filter((o) => o.terrainRole !== 'base');
  return [...dems, ...rest];
}

interface WorkflowState {
  step: WorkflowStep;
  place: PlaceSelection | null;
  scenes: SceneSummary[];
  visibleSceneIds: string[];
  focusSceneId: string | null;
  analysisOpen: boolean;
  terrainOpen: boolean;
  toolboxOpen: boolean;
  expandedToolbox: string | null;
  mapChrome: {
    compass: boolean;
    scaleBar: boolean;
    coordinates: boolean;
    grid: boolean;
    miniMap: boolean;
    swipe: boolean;
    splitView: boolean;
    syncMaps: boolean;
    rotate: boolean;
    view3d: boolean;
    terrainRelief: boolean;
    timeSlider: boolean;
    bookmarks: boolean;
    manualVerify: boolean;
  };
  compareSceneId: string | null;
  indexResult: IndexResult | null;
  changeResult: ChangeResult | null;
  selectedIndex: IndexName | null;
  loadingScenes: boolean;
  loadingIndex: boolean;
  loadingOverlayIds: string[];
  error: string | null;
  mapTool: MapTool;
  aoiGeoJson: GeoJSON.Feature | null;
  drawnFeature: DrawnFeature | null;
  measureLine: GeoJSON.LineString | null;
  bufferGeoJson: GeoJSON.Polygon | null;
  measureLabel: string | null;
  overlays: MapOverlay[];
  layerOpacity: number;
  setStep: (step: WorkflowStep) => void;
  setPlace: (place: PlaceSelection) => void;
  setScenes: (scenes: SceneSummary[]) => void;
  setFocusSceneId: (id: string | null) => void;
  setAnalysisOpen: (open: boolean) => void;
  setTerrainOpen: (open: boolean) => void;
  setToolboxOpen: (open: boolean) => void;
  setExpandedToolbox: (id: string | null) => void;
  setMapChrome: (patch: Partial<WorkflowState['mapChrome']>) => void;
  toggleMapChrome: (key: keyof WorkflowState['mapChrome']) => void;
  setCompareSceneId: (id: string | null) => void;
  setIndexResult: (result: IndexResult | null) => void;
  setChangeResult: (result: ChangeResult | null) => void;
  setSelectedIndex: (index: IndexName | null) => void;
  setLoadingScenes: (v: boolean) => void;
  setLoadingIndex: (v: boolean) => void;
  addLoadingOverlay: (id: string) => void;
  removeLoadingOverlay: (id: string) => void;
  setError: (error: string | null) => void;
  setMapTool: (tool: MapTool) => void;
  setAoiGeoJson: (f: GeoJSON.Feature | null) => void;
  setDrawnFeature: (f: DrawnFeature | null) => void;
  setMeasureLine: (line: GeoJSON.LineString | null) => void;
  setBufferGeoJson: (g: GeoJSON.Polygon | null) => void;
  setMeasureLabel: (label: string | null) => void;
  upsertOverlay: (overlay: MapOverlay) => void;
  removeOverlay: (id: string) => void;
  removeOverlaysByKind: (kind: MapOverlay['kind']) => void;
  removeSceneOverlay: (sceneId: string) => void;
  setOverlayVisible: (id: string, visible: boolean) => void;
  renameOverlay: (id: string, label: string) => void;
  moveOverlay: (id: string, dir: 'up' | 'down') => void;
  /** Reorder overlays from Layer Manager display order (top of list = top of map). */
  reorderOverlaysDisplay: (displayIds: string[]) => void;
  patchOverlay: (id: string, patch: Partial<MapOverlay>) => void;
  duplicateOverlay: (id: string) => void;
  setLayerOpacity: (opacity: number) => void;
  showScene: (sceneId: string) => void;
  hideScene: (sceneId: string) => void;
  clearAnalysis: () => void;
  clearDrawn: () => void;
  resetFromPlace: () => void;
  backToPlace: () => void;
}

export const useWorkflowStore = create<WorkflowState>((set) => ({
  step: 'place',
  place: null,
  scenes: [],
  visibleSceneIds: [],
  focusSceneId: null,
  analysisOpen: false,
  terrainOpen: false,
  toolboxOpen: true,
  expandedToolbox: 'image',
  mapChrome: {
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
  },
  compareSceneId: null,
  indexResult: null,
  changeResult: null,
  selectedIndex: null,
  loadingScenes: false,
  loadingIndex: false,
  loadingOverlayIds: [],
  error: null,
  mapTool: 'navigate',
  aoiGeoJson: null,
  drawnFeature: null,
  measureLine: null,
  bufferGeoJson: null,
  measureLabel: null,
  overlays: [],
  layerOpacity: 0.8,

  setStep: (step) => set({ step }),
  setPlace: (place) => set({ place }),
  setScenes: (scenes) => set({ scenes }),
  setFocusSceneId: (focusSceneId) => set({ focusSceneId }),
  setAnalysisOpen: (analysisOpen) => set({ analysisOpen }),
  setTerrainOpen: (terrainOpen) => set({ terrainOpen }),
  setToolboxOpen: (toolboxOpen) => set({ toolboxOpen }),
  setExpandedToolbox: (expandedToolbox) => set({ expandedToolbox }),
  setMapChrome: (patch) => set((s) => ({ mapChrome: { ...s.mapChrome, ...patch } })),
  toggleMapChrome: (key) =>
    set((s) => ({ mapChrome: { ...s.mapChrome, [key]: !s.mapChrome[key] } })),
  setCompareSceneId: (compareSceneId) => set({ compareSceneId }),
  setIndexResult: (indexResult) => set({ indexResult }),
  setChangeResult: (changeResult) => set({ changeResult }),
  setSelectedIndex: (selectedIndex) => set({ selectedIndex }),
  setLoadingScenes: (loadingScenes) => set({ loadingScenes }),
  setLoadingIndex: (loadingIndex) => set({ loadingIndex }),
  addLoadingOverlay: (id) =>
    set((s) => ({
      loadingOverlayIds: s.loadingOverlayIds.includes(id)
        ? s.loadingOverlayIds
        : [...s.loadingOverlayIds, id],
    })),
  removeLoadingOverlay: (id) =>
    set((s) => ({ loadingOverlayIds: s.loadingOverlayIds.filter((x) => x !== id) })),
  setError: (error) => set({ error }),
  setMapTool: (mapTool) => set({ mapTool }),
  setAoiGeoJson: (aoiGeoJson) => set({ aoiGeoJson }),
  setDrawnFeature: (drawnFeature) => set({ drawnFeature }),
  setMeasureLine: (measureLine) => set({ measureLine }),
  setBufferGeoJson: (bufferGeoJson) => set({ bufferGeoJson }),
  setMeasureLabel: (measureLabel) => set({ measureLabel }),

  upsertOverlay: (overlay) =>
    set((state) => {
      let next = state.overlays.filter((o) => o.id !== overlay.id);
      if (overlay.kind === 'index' || overlay.kind === 'change' || overlay.kind === 'detection') {
        next = next.filter((o) => o.kind !== overlay.kind);
      }
      // Keep DEM base when swapping analysis terrain products
      if (overlay.kind === 'terrain') {
        if (overlay.terrainRole === 'base') {
          next = next.filter((o) => !(o.kind === 'terrain' && o.terrainRole === 'base'));
        } else {
          next = next.filter(
            (o) => !(o.kind === 'terrain' && o.terrainRole !== 'base'),
          );
        }
      }
      if (overlay.kind === 'buffer') {
        next = next.filter((o) => o.kind !== 'buffer');
      }
      if (overlay.kind === 'scene' && overlay.sceneId) {
        next = next.filter((o) => !(o.kind === 'scene' && o.sceneId === overlay.sceneId));
      }
      const item = { visible: true, ...overlay };
      next = [...next, item];
      // New DEM base starts at the back; later Layer Manager reorder is free
      if (overlay.terrainRole === 'base') {
        return { overlays: pinDemBaseToBack(next) };
      }
      return { overlays: next };
    }),

  removeOverlay: (id) =>
    set((state) => ({ overlays: state.overlays.filter((o) => o.id !== id) })),

  removeOverlaysByKind: (kind) =>
    set((state) => ({ overlays: state.overlays.filter((o) => o.kind !== kind) })),

  removeSceneOverlay: (sceneId) =>
    set((state) => ({
      overlays: state.overlays.filter(
        (o) => !(o.kind === 'scene' && o.sceneId === sceneId),
      ),
    })),

  setOverlayVisible: (id, visible) =>
    set((state) => ({
      overlays: state.overlays.map((o) => (o.id === id ? { ...o, visible } : o)),
    })),

  renameOverlay: (id, label) =>
    set((state) => ({
      overlays: state.overlays.map((o) => (o.id === id ? { ...o, label } : o)),
    })),

  moveOverlay: (id, dir) =>
    set((state) => {
      const display = [...state.overlays].reverse();
      const idx = display.findIndex((o) => o.id === id);
      if (idx < 0) return state;
      const target = dir === 'up' ? idx - 1 : idx + 1;
      if (target < 0 || target >= display.length) return state;
      const moving = display[idx];
      const swapWith = display[target];
      // DEM base stays under imagery in the unified stack
      if (moving.terrainRole === 'base' && dir === 'up') return state;
      if (swapWith.terrainRole === 'base' && dir === 'down') return state;
      const nextDisplay = [...display];
      const [item] = nextDisplay.splice(idx, 1);
      nextDisplay.splice(target, 0, item);
      return { overlays: pinDemBaseToBack(nextDisplay.reverse()) };
    }),

  reorderOverlaysDisplay: (displayIds) =>
    set((state) => {
      const byId = new Map(state.overlays.map((o) => [o.id, o]));
      const ordered: MapOverlay[] = [];
      for (const id of displayIds) {
        const o = byId.get(id);
        if (o) {
          ordered.push(o);
          byId.delete(id);
        }
      }
      for (const o of byId.values()) ordered.push(o);
      return { overlays: pinDemBaseToBack(ordered.reverse()) };
    }),

  patchOverlay: (id, patch) =>
    set((state) => ({
      overlays: state.overlays.map((o) => (o.id === id ? { ...o, ...patch } : o)),
    })),

  duplicateOverlay: (id) =>
    set((state) => {
      const src = state.overlays.find((o) => o.id === id);
      if (!src) return state;
      const copy: MapOverlay = {
        ...src,
        id: `${src.id}-copy-${Date.now()}`,
        label: `${src.label} (copy)`,
      };
      return { overlays: [...state.overlays, copy] };
    }),

  setLayerOpacity: (layerOpacity) =>
    set((state) => ({
      layerOpacity,
      overlays: state.overlays.map((o) =>
        o.kind === 'scene' ? o : { ...o, opacity: layerOpacity },
      ),
    })),

  showScene: (sceneId) =>
    set((state) => ({
      visibleSceneIds: state.visibleSceneIds.includes(sceneId)
        ? state.visibleSceneIds
        : [...state.visibleSceneIds, sceneId],
      focusSceneId: sceneId,
    })),

  hideScene: (sceneId) =>
    set((state) => {
      const visibleSceneIds = state.visibleSceneIds.filter((id) => id !== sceneId);
      const focusSceneId =
        state.focusSceneId === sceneId
          ? visibleSceneIds[visibleSceneIds.length - 1] ?? null
          : state.focusSceneId;
      const clearAnalysis = visibleSceneIds.length === 0;
      return {
        visibleSceneIds,
        focusSceneId,
        analysisOpen: clearAnalysis ? false : state.analysisOpen,
        terrainOpen: clearAnalysis ? false : state.terrainOpen,
        indexResult: clearAnalysis ? null : state.indexResult,
        changeResult: clearAnalysis ? null : state.changeResult,
        selectedIndex: clearAnalysis ? null : state.selectedIndex,
        compareSceneId: clearAnalysis ? null : state.compareSceneId,
        overlays: clearAnalysis
          ? state.overlays.filter((o) => o.kind === 'scene' && o.sceneId !== sceneId)
          : state.overlays.filter(
              (o) => !(o.kind === 'scene' && o.sceneId === sceneId),
            ),
      };
    }),

  clearAnalysis: () =>
    set((state) => ({
      indexResult: null,
      changeResult: null,
      selectedIndex: null,
      compareSceneId: null,
      overlays: state.overlays.filter(
        (o) => o.kind === 'scene' || o.kind === 'terrain' || o.kind === 'buffer',
      ),
    })),

  clearDrawn: () =>
    set((state) => ({
      aoiGeoJson: null,
      drawnFeature: null,
      measureLine: null,
      bufferGeoJson: null,
      measureLabel: null,
      overlays: state.overlays.filter((o) => o.kind !== 'buffer'),
    })),

  resetFromPlace: () =>
    set({
      step: 'browse',
      scenes: [],
      visibleSceneIds: [],
      focusSceneId: null,
      analysisOpen: false,
      terrainOpen: false,
      toolboxOpen: true,
      expandedToolbox: 'image',
      compareSceneId: null,
      indexResult: null,
      changeResult: null,
      selectedIndex: null,
      error: null,
      overlays: [],
      measureLabel: null,
      loadingOverlayIds: [],
    }),

  backToPlace: () =>
    set({
      step: 'place',
      place: null,
      scenes: [],
      visibleSceneIds: [],
      focusSceneId: null,
      analysisOpen: false,
      terrainOpen: false,
      toolboxOpen: true,
      expandedToolbox: 'image',
      compareSceneId: null,
      indexResult: null,
      changeResult: null,
      selectedIndex: null,
      error: null,
      loadingScenes: false,
      loadingIndex: false,
      loadingOverlayIds: [],
      overlays: [],
      aoiGeoJson: null,
      drawnFeature: null,
      measureLine: null,
      bufferGeoJson: null,
      measureLabel: null,
      mapTool: 'navigate',
    }),
}));
