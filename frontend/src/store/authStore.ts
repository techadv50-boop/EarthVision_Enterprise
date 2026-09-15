import { create } from 'zustand';
import { authApi } from '@/services/api';

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

export function isCitationAdmin(user: User | null | undefined): boolean {
  if (!user) return false;
  return Boolean(user.is_superuser || (user.roles || []).includes('admin'));
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  fetchUser: () => Promise<void>;
}

function clearStoredTokens() {
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: !!localStorage.getItem('access_token'),
  // Never start true: leftover tokens used to disable Sign In forever.
  isLoading: false,

  login: async (username, password) => {
    try {
      const { data } = await authApi.login(username, password);
      if (!data?.access_token) {
        throw new Error('Login did not return a token');
      }
      localStorage.setItem('access_token', data.access_token);
      localStorage.setItem('refresh_token', data.refresh_token);
      const { data: user } = await authApi.me();
      set({ user, isAuthenticated: true, isLoading: false });
    } catch (error) {
      clearStoredTokens();
      set({ user: null, isAuthenticated: false, isLoading: false });
      throw error;
    }
  },

  logout: () => {
    clearStoredTokens();
    set({ user: null, isAuthenticated: false, isLoading: false });
  },

  fetchUser: async () => {
    if (!localStorage.getItem('access_token')) {
      set({ user: null, isAuthenticated: false, isLoading: false });
      return;
    }
    set({ isLoading: true });
    try {
      const { data } = await authApi.me();
      set({ user: data, isAuthenticated: true, isLoading: false });
    } catch {
      clearStoredTokens();
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },
}));
