import { create } from 'zustand';
import type { SceneSummary } from '../services/catalogService';
import type { IndexName, IndexResult, ChangeResult } from '../services/analyticsService';

export type WorkflowStep = 'place' | 'scenes' | 'analyze';
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
  url: string;
  bounds: [number, number, number, number];
  opacity: number;
  label: string;
}

interface WorkflowState {
  step: WorkflowStep;
  place: PlaceSelection | null;
  scenes: SceneSummary[];
  selectedScene: SceneSummary | null;
  compareScene: SceneSummary | null;
  indexResult: IndexResult | null;
  changeResult: ChangeResult | null;
  selectedIndex: IndexName | null;
  loadingScenes: boolean;
  loadingIndex: boolean;
  loadingOverlay: boolean;
  error: string | null;
  mapTool: MapTool;
  aoiGeoJson: GeoJSON.Feature | null;
  measureLabel: string | null;
  overlays: MapOverlay[];
  activeOverlayId: string | null;
  layerOpacity: number;
  setStep: (step: WorkflowStep) => void;
  setPlace: (place: PlaceSelection) => void;
  setScenes: (scenes: SceneSummary[]) => void;
  setSelectedScene: (scene: SceneSummary | null) => void;
  setCompareScene: (scene: SceneSummary | null) => void;
  setIndexResult: (result: IndexResult | null) => void;
  setChangeResult: (result: ChangeResult | null) => void;
  setSelectedIndex: (index: IndexName | null) => void;
  setLoadingScenes: (v: boolean) => void;
  setLoadingIndex: (v: boolean) => void;
  setLoadingOverlay: (v: boolean) => void;
  setError: (error: string | null) => void;
  setMapTool: (tool: MapTool) => void;
  setAoiGeoJson: (f: GeoJSON.Feature | null) => void;
  setMeasureLabel: (label: string | null) => void;
  upsertOverlay: (overlay: MapOverlay) => void;
  removeOverlay: (id: string) => void;
  setActiveOverlayId: (id: string | null) => void;
  setLayerOpacity: (opacity: number) => void;
  resetFromPlace: () => void;
  backToScenes: () => void;
  backToPlace: () => void;
}

export const useWorkflowStore = create<WorkflowState>((set) => ({
  step: 'place',
  place: null,
  scenes: [],
  selectedScene: null,
  compareScene: null,
  indexResult: null,
  changeResult: null,
  selectedIndex: null,
  loadingScenes: false,
  loadingIndex: false,
  loadingOverlay: false,
  error: null,
  mapTool: 'navigate',
  aoiGeoJson: null,
  measureLabel: null,
  overlays: [],
  activeOverlayId: null,
  layerOpacity: 0.75,

  setStep: (step) => set({ step }),
  setPlace: (place) => set({ place }),
  setScenes: (scenes) => set({ scenes }),
  setSelectedScene: (selectedScene) => set({ selectedScene }),
  setCompareScene: (compareScene) => set({ compareScene }),
  setIndexResult: (indexResult) => set({ indexResult }),
  setChangeResult: (changeResult) => set({ changeResult }),
  setSelectedIndex: (selectedIndex) => set({ selectedIndex }),
  setLoadingScenes: (loadingScenes) => set({ loadingScenes }),
  setLoadingIndex: (loadingIndex) => set({ loadingIndex }),
  setLoadingOverlay: (loadingOverlay) => set({ loadingOverlay }),
  setError: (error) => set({ error }),
  setMapTool: (mapTool) => set({ mapTool }),
  setAoiGeoJson: (aoiGeoJson) => set({ aoiGeoJson }),
  setMeasureLabel: (measureLabel) => set({ measureLabel }),
  upsertOverlay: (overlay) =>
    set((state) => {
      const cleaned = state.overlays.filter((o) => o.kind !== overlay.kind);
      return { overlays: [...cleaned, overlay], activeOverlayId: overlay.id };
    }),
  removeOverlay: (id) =>
    set((state) => ({
      overlays: state.overlays.filter((o) => o.id !== id),
      activeOverlayId: state.activeOverlayId === id ? null : state.activeOverlayId,
    })),
  setActiveOverlayId: (activeOverlayId) => set({ activeOverlayId }),
  setLayerOpacity: (layerOpacity) =>
    set((state) => ({
      layerOpacity,
      overlays: state.overlays.map((o) =>
        !state.activeOverlayId || o.id === state.activeOverlayId
          ? { ...o, opacity: layerOpacity }
          : o,
      ),
    })),

  resetFromPlace: () =>
    set({
      step: 'scenes',
      scenes: [],
      selectedScene: null,
      compareScene: null,
      indexResult: null,
      changeResult: null,
      selectedIndex: null,
      error: null,
      overlays: [],
      activeOverlayId: null,
      measureLabel: null,
    }),

  backToScenes: () =>
    set((state) => ({
      step: 'scenes',
      selectedScene: null,
      compareScene: null,
      indexResult: null,
      changeResult: null,
      selectedIndex: null,
      error: null,
      overlays: state.overlays.filter((o) => o.kind === 'scene'),
      activeOverlayId: state.overlays.find((o) => o.kind === 'scene')?.id ?? null,
    })),

  backToPlace: () =>
    set({
      step: 'place',
      place: null,
      scenes: [],
      selectedScene: null,
      compareScene: null,
      indexResult: null,
      changeResult: null,
      selectedIndex: null,
      error: null,
      loadingScenes: false,
      loadingIndex: false,
      overlays: [],
      activeOverlayId: null,
      aoiGeoJson: null,
      measureLabel: null,
      mapTool: 'navigate',
    }),
}));
