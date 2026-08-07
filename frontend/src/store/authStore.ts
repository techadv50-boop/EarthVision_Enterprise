import { create } from 'zustand';
import { authApi, configApi } from '@/services/api';

interface User {
  id: number;
  email: string;
  username: string;
  full_name?: string;
  organization?: string;
  is_active: boolean;
  is_superuser: boolean;
  roles: string[];
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  offlineMode: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  fetchUser: () => Promise<void>;
}

const OFFLINE_USER: User = {
  id: 0,
  email: 'offline@sateye.local',
  username: 'offline',
  full_name: 'SAT EYE Offline Operator',
  is_active: true,
  is_superuser: true,
  roles: ['analyst'],
};

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: !!localStorage.getItem('access_token'),
  isLoading: true,
  offlineMode: true,

  login: async (username, password) => {
    set({ isLoading: true });
    try {
      const { data } = await authApi.login(username, password);
      localStorage.setItem('access_token', data.access_token);
      localStorage.setItem('refresh_token', data.refresh_token);
      const { data: user } = await authApi.me();
      set({ user, isAuthenticated: true, isLoading: false });
    } catch (error) {
      set({ isLoading: false });
      throw error;
    }
  },

  logout: () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    // In offline mode stay signed in as local operator
    set({ user: OFFLINE_USER, isAuthenticated: true, offlineMode: true });
  },

  fetchUser: async () => {
    set({ isLoading: true });
    try {
      const { data: cfg } = await configApi.config();
      const offline = cfg.offline_mode !== false;
      if (offline) {
        // Offline PC mode: no login wall — local operator session
        try {
          const { data } = await authApi.me();
          set({
            user: data,
            isAuthenticated: true,
            isLoading: false,
            offlineMode: true,
          });
        } catch {
          set({
            user: OFFLINE_USER,
            isAuthenticated: true,
            isLoading: false,
            offlineMode: true,
          });
        }
        return;
      }

      if (!localStorage.getItem('access_token')) {
        set({ user: null, isAuthenticated: false, isLoading: false, offlineMode: false });
        return;
      }
      const { data } = await authApi.me();
      set({ user: data, isAuthenticated: true, isLoading: false, offlineMode: false });
    } catch {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      // Prefer offline fallback so the desktop app still opens
      set({
        user: OFFLINE_USER,
        isAuthenticated: true,
        isLoading: false,
        offlineMode: true,
      });
    }
  },
}));
