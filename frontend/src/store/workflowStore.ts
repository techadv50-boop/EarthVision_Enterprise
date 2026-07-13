import { create } from 'zustand';
import type { SceneSummary } from '../services/catalogService';
import type { IndexName, IndexResult } from '../services/analyticsService';

export type WorkflowStep = 'place' | 'scenes' | 'analyze';

export interface PlaceSelection {
  name: string;
  longitude: number;
  latitude: number;
  bbox: [number, number, number, number]; // west,south,east,north
}

interface WorkflowState {
  step: WorkflowStep;
  place: PlaceSelection | null;
  scenes: SceneSummary[];
  selectedScene: SceneSummary | null;
  indexResult: IndexResult | null;
  selectedIndex: IndexName | null;
  loadingScenes: boolean;
  loadingIndex: boolean;
  error: string | null;
  setStep: (step: WorkflowStep) => void;
  setPlace: (place: PlaceSelection) => void;
  setScenes: (scenes: SceneSummary[]) => void;
  setSelectedScene: (scene: SceneSummary | null) => void;
  setIndexResult: (result: IndexResult | null) => void;
  setSelectedIndex: (index: IndexName | null) => void;
  setLoadingScenes: (v: boolean) => void;
  setLoadingIndex: (v: boolean) => void;
  setError: (error: string | null) => void;
  resetFromPlace: () => void;
  backToScenes: () => void;
  backToPlace: () => void;
}

export const useWorkflowStore = create<WorkflowState>((set) => ({
  step: 'place',
  place: null,
  scenes: [],
  selectedScene: null,
  indexResult: null,
  selectedIndex: null,
  loadingScenes: false,
  loadingIndex: false,
  error: null,

  setStep: (step) => set({ step }),
  setPlace: (place) => set({ place }),
  setScenes: (scenes) => set({ scenes }),
  setSelectedScene: (selectedScene) => set({ selectedScene }),
  setIndexResult: (indexResult) => set({ indexResult }),
  setSelectedIndex: (selectedIndex) => set({ selectedIndex }),
  setLoadingScenes: (loadingScenes) => set({ loadingScenes }),
  setLoadingIndex: (loadingIndex) => set({ loadingIndex }),
  setError: (error) => set({ error }),

  resetFromPlace: () =>
    set({
      step: 'scenes',
      scenes: [],
      selectedScene: null,
      indexResult: null,
      selectedIndex: null,
      error: null,
    }),

  backToScenes: () =>
    set({
      step: 'scenes',
      selectedScene: null,
      indexResult: null,
      selectedIndex: null,
      error: null,
    }),

  backToPlace: () =>
    set({
      step: 'place',
      place: null,
      scenes: [],
      selectedScene: null,
      indexResult: null,
      selectedIndex: null,
      error: null,
      loadingScenes: false,
      loadingIndex: false,
    }),
}));
