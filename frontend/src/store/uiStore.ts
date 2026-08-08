import { create } from 'zustand';

export type PanelId =
  | 'layers'
  | 'search'
  | 'imagery'
  | 'upload'
  | 'analytics'
  | 'bookmarks'
  | 'aoi'
  | 'raster'
  | 'tools'
  | 'admin'
  | null;

interface UIState {
  sidebarOpen: boolean;
  activePanel: PanelId;
  toggleSidebar: () => void;
  setActivePanel: (panel: PanelId) => void;
  isLoading: boolean;
  setLoading: (loading: boolean) => void;
  notification: { message: string; type: 'success' | 'error' | 'info' } | null;
  showNotification: (message: string, type?: 'success' | 'error' | 'info') => void;
  clearNotification: () => void;
}

export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: true,
  activePanel: null,
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setActivePanel: (panel) =>
    set((s) => ({
      activePanel: s.activePanel === panel ? null : panel,
    })),
  isLoading: false,
  setLoading: (loading) => set({ isLoading: loading }),
  notification: null,
  showNotification: (message, type = 'info') => {
    set({ notification: { message, type } });
    setTimeout(() => set({ notification: null }), 4000);
  },
  clearNotification: () => set({ notification: null }),
}));
