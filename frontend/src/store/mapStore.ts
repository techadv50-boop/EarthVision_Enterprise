import { create } from 'zustand';
import type { SceneSummary } from '../services/catalogService';
import type { Bookmark } from '../services/bookmarkService';
import type { IndexResult, IndexName } from '../services/analyticsService';

export type DrawMode = 'none' | 'polygon' | 'rectangle' | 'circle' | 'measure';
export type ActivePanel =
  | 'none'
  | 'layers'
  | 'search'
  | 'catalog'
  | 'analytics'
  | 'ml'
  | 'bookmarks'
  | 'projects'
  | 'admin'
  | 'aoi';

interface MouseCoords {
  longitude: number;
  latitude: number;
  height: number;
}

interface MapState {
  mouseCoords: MouseCoords | null;
  cameraHeading: number;
  drawMode: DrawMode;
  activePanel: ActivePanel;
  aoiGeoJson: GeoJSON.Feature | null;
  markers: Array<{ id: string; lon: number; lat: number; label: string }>;
  scenes: SceneSummary[];
  selectedScene: SceneSummary | null;
  footprintsVisible: boolean;
  bookmarks: Bookmark[];
  baseLayer: 'imagery' | 'osm' | 'terrain';
  terrainEnabled: boolean;
  indexResult: IndexResult | null;
  selectedIndex: IndexName;
  measurementLabel: string | null;
  setMouseCoords: (coords: MouseCoords | null) => void;
  setCameraHeading: (h: number) => void;
  setDrawMode: (mode: DrawMode) => void;
  setActivePanel: (panel: ActivePanel) => void;
  setAoi: (feature: GeoJSON.Feature | null) => void;
  addMarker: (marker: { lon: number; lat: number; label: string }) => void;
  clearMarkers: () => void;
  setScenes: (scenes: SceneSummary[]) => void;
  setSelectedScene: (scene: SceneSummary | null) => void;
  setFootprintsVisible: (v: boolean) => void;
  setBookmarks: (bookmarks: Bookmark[]) => void;
  setBaseLayer: (layer: 'imagery' | 'osm' | 'terrain') => void;
  setTerrainEnabled: (v: boolean) => void;
  setIndexResult: (r: IndexResult | null) => void;
  setSelectedIndex: (i: IndexName) => void;
  setMeasurementLabel: (label: string | null) => void;
}

export const useMapStore = create<MapState>((set) => ({
  mouseCoords: null,
  cameraHeading: 0,
  drawMode: 'none',
  activePanel: 'none',
  aoiGeoJson: null,
  markers: [],
  scenes: [],
  selectedScene: null,
  footprintsVisible: true,
  bookmarks: [],
  baseLayer: 'imagery',
  terrainEnabled: true,
  indexResult: null,
  selectedIndex: 'NDVI',
  measurementLabel: null,

  setMouseCoords: (mouseCoords) => set({ mouseCoords }),
  setCameraHeading: (cameraHeading) => set({ cameraHeading }),
  setDrawMode: (drawMode) => set({ drawMode }),
  setActivePanel: (activePanel) =>
    set((state) => ({
      activePanel: state.activePanel === activePanel ? 'none' : activePanel,
    })),
  setAoi: (aoiGeoJson) => set({ aoiGeoJson }),
  addMarker: (marker) =>
    set((state) => ({
      markers: [...state.markers, { ...marker, id: crypto.randomUUID() }],
    })),
  clearMarkers: () => set({ markers: [] }),
  setScenes: (scenes) => set({ scenes }),
  setSelectedScene: (selectedScene) => set({ selectedScene }),
  setFootprintsVisible: (footprintsVisible) => set({ footprintsVisible }),
  setBookmarks: (bookmarks) => set({ bookmarks }),
  setBaseLayer: (baseLayer) => set({ baseLayer }),
  setTerrainEnabled: (terrainEnabled) => set({ terrainEnabled }),
  setIndexResult: (indexResult) => set({ indexResult }),
  setSelectedIndex: (selectedIndex) => set({ selectedIndex }),
  setMeasurementLabel: (measurementLabel) => set({ measurementLabel }),
}));
