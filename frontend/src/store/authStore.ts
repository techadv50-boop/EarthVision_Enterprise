import { create } from 'zustand';
import { authService, type User } from '../services/authService';
import { getErrorMessage } from '../services/api';

interface AuthState {
  user: User | null;
  loading: boolean;
  error: string | null;
  initialized: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (payload: {
    email: string;
    password: string;
    full_name: string;
    organization?: string;
  }) => Promise<void>;
  logout: () => void;
  loadUser: () => Promise<void>;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  loading: false,
  error: null,
  initialized: false,

  login: async (email, password) => {
    set({ loading: true, error: null });
    try {
      await authService.login(email, password);
      const user = await authService.me();
      set({ user, loading: false, initialized: true });
    } catch (error) {
      set({ error: getErrorMessage(error), loading: false });
      throw error;
    }
  },

  register: async (payload) => {
    set({ loading: true, error: null });
    try {
      await authService.register(payload);
      await authService.login(payload.email, payload.password);
      const user = await authService.me();
      set({ user, loading: false, initialized: true });
    } catch (error) {
      set({ error: getErrorMessage(error), loading: false });
      throw error;
    }
  },

  logout: () => {
    authService.logout();
    set({ user: null });
  },

  loadUser: async () => {
    if (!authService.isAuthenticated()) {
      set({ initialized: true, user: null });
      return;
    }
    try {
      const user = await authService.me();
      set({ user, initialized: true });
    } catch {
      authService.logout();
      set({ user: null, initialized: true });
    }
  },

  clearError: () => set({ error: null }),
}));
