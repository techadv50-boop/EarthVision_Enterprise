import { create } from 'zustand';
import type { SceneSummary } from '../services/catalogService';
import type { IndexName, IndexResult, ChangeResult } from '../services/analyticsService';

export type WorkflowStep = 'place' | 'browse';
export type MapTool =
  | 'navigate'
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
  kind: 'scene' | 'index' | 'change';
  sceneId?: string;
  /** Static image URL (indices / change). Empty when using tileUrl. */
  url: string;
  /** XYZ tile template for sharp Sentinel-2 true-color scene layers */
  tileUrl?: string;
  bounds: [number, number, number, number];
  opacity: number;
  label: string;
}

interface WorkflowState {
  step: WorkflowStep;
  place: PlaceSelection | null;
  scenes: SceneSummary[];
  visibleSceneIds: string[];
  focusSceneId: string | null;
  analysisOpen: boolean;
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
  measureLabel: string | null;
  overlays: MapOverlay[];
  layerOpacity: number;
  setStep: (step: WorkflowStep) => void;
  setPlace: (place: PlaceSelection) => void;
  setScenes: (scenes: SceneSummary[]) => void;
  setFocusSceneId: (id: string | null) => void;
  setAnalysisOpen: (open: boolean) => void;
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
  setMeasureLabel: (label: string | null) => void;
  upsertOverlay: (overlay: MapOverlay) => void;
  removeOverlay: (id: string) => void;
  removeOverlaysByKind: (kind: MapOverlay['kind']) => void;
  removeSceneOverlay: (sceneId: string) => void;
  setLayerOpacity: (opacity: number) => void;
  showScene: (sceneId: string) => void;
  hideScene: (sceneId: string) => void;
  clearAnalysis: () => void;
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
  measureLabel: null,
  overlays: [],
  layerOpacity: 0.8,

  setStep: (step) => set({ step }),
  setPlace: (place) => set({ place }),
  setScenes: (scenes) => set({ scenes }),
  setFocusSceneId: (focusSceneId) => set({ focusSceneId }),
  setAnalysisOpen: (analysisOpen) => set({ analysisOpen }),
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
  setMeasureLabel: (measureLabel) => set({ measureLabel }),

  upsertOverlay: (overlay) =>
    set((state) => {
      let next = state.overlays.filter((o) => o.id !== overlay.id);
      if (overlay.kind === 'index' || overlay.kind === 'change') {
        next = next.filter((o) => o.kind !== overlay.kind);
      }
      if (overlay.kind === 'scene' && overlay.sceneId) {
        next = next.filter((o) => !(o.kind === 'scene' && o.sceneId === overlay.sceneId));
      }
      return { overlays: [...next, overlay] };
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

  setLayerOpacity: (layerOpacity) =>
    set((state) => ({
      layerOpacity,
      overlays: state.overlays.map((o) => ({ ...o, opacity: layerOpacity })),
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
      overlays: state.overlays.filter((o) => o.kind === 'scene'),
    })),

  resetFromPlace: () =>
    set({
      step: 'browse',
      scenes: [],
      visibleSceneIds: [],
      focusSceneId: null,
      analysisOpen: false,
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
      measureLabel: null,
      mapTool: 'navigate',
    }),
}));
