import { create } from 'zustand';
import { offlineApi } from '@/services/api';

export interface StackImage {
  id: string;
  file_path: string;
  acquisition_date: string;
  label?: string;
  cloud_cover?: number;
  metadata?: Record<string, unknown>;
  footprint_geojson?: string;
  is_demo?: boolean;
}

export interface ImageryStack {
  id: string;
  name: string;
  place_key: string;
  longitude?: number;
  latitude?: number;
  description?: string;
  image_count: number;
  date_min?: string;
  date_max?: string;
  has_slider: boolean;
  images: StackImage[];
}

interface StackState {
  stacks: ImageryStack[];
  activeStack: ImageryStack | null;
  sliderIndex: number;
  loading: boolean;
  loadStacks: () => Promise<void>;
  setActiveStack: (stack: ImageryStack | null) => void;
  setSliderIndex: (index: number) => void;
  selectByDateIndex: (index: number) => StackImage | null;
  ensureDemoStack: () => Promise<void>;
}

export const useStackStore = create<StackState>((set, get) => ({
  stacks: [],
  activeStack: null,
  sliderIndex: 0,
  loading: false,

  loadStacks: async () => {
    set({ loading: true });
    try {
      const { data } = await offlineApi.stacks();
      const stacks = (data.stacks || []) as ImageryStack[];
      set({ stacks, loading: false });
      const current = get().activeStack;
      if (current) {
        const refreshed = stacks.find((s) => s.id === current.id) || null;
        set({ activeStack: refreshed });
      } else if (stacks.length > 0) {
        const preferred =
          stacks.find((s) => s.image_count >= 2) || stacks[0];
        set({
          activeStack: preferred,
          sliderIndex: Math.max(0, preferred.images.length - 1),
        });
      }
    } catch {
      set({ loading: false });
    }
  },

  setActiveStack: (stack) =>
    set({
      activeStack: stack,
      sliderIndex: stack ? Math.max(0, stack.images.length - 1) : 0,
    }),

  setSliderIndex: (index) => {
    const stack = get().activeStack;
    if (!stack) return;
    const clamped = Math.max(0, Math.min(index, stack.images.length - 1));
    set({ sliderIndex: clamped });
  },

  selectByDateIndex: (index) => {
    const stack = get().activeStack;
    if (!stack || !stack.images.length) return null;
    const clamped = Math.max(0, Math.min(index, stack.images.length - 1));
    set({ sliderIndex: clamped });
    return stack.images[clamped];
  },

  ensureDemoStack: async () => {
    await offlineApi.seedDemoStack();
    await get().loadStacks();
  },
}));
