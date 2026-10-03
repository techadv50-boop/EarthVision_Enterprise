import { create } from 'zustand';
import { authApi } from '@/services/api';

export const ADMIN_DESKS = [
  { id: 'citation', label: 'Citation project', hint: 'Journals, archive, and manuscripts' },
  { id: 'authors', label: 'Author database', hint: 'Under process and published records' },
  { id: 'review', label: 'Article review', hint: 'Reference check and English review' },
  { id: 'users', label: 'Adding users', hint: 'Create accounts and assign desks' },
  { id: 'galley', label: 'Galley composition', hint: 'Journal shelf and Word proofs' },
] as const;

export type AdminDeskId = (typeof ADMIN_DESKS)[number]['id'];

interface User {
  id: number;
  email: string;
  username: string;
  full_name?: string;
  organization?: string;
  is_active: boolean;
  is_superuser: boolean;
  roles: string[];
  desks?: string[];
}

function desksFromRoles(user: User | null | undefined): AdminDeskId[] {
  if (!user) return [];
  if (user.desks && user.desks.length) {
    return ADMIN_DESKS.map((d) => d.id).filter((id) => user.desks!.includes(id));
  }
  if (user.is_superuser || (user.roles || []).includes('admin')) {
    return ADMIN_DESKS.map((d) => d.id);
  }
  return ADMIN_DESKS.map((d) => d.id).filter((id) => (user.roles || []).includes(`admin_${id}`));
}

export function isFullAdmin(user: User | null | undefined): boolean {
  if (!user) return false;
  return Boolean(user.is_superuser || (user.roles || []).includes('admin'));
}

export function hasDesk(user: User | null | undefined, desk: AdminDeskId): boolean {
  return desksFromRoles(user).includes(desk);
}

export function hasAnyDesk(user: User | null | undefined): boolean {
  return desksFromRoles(user).length > 0;
}

export function deskList(user: User | null | undefined): AdminDeskId[] {
  return desksFromRoles(user);
}

export function isCitationAdmin(user: User | null | undefined): boolean {
  return hasDesk(user, 'citation');
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  fetchUser: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: !!localStorage.getItem('access_token'),
  isLoading: !!localStorage.getItem('access_token'),

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
    set({ user: null, isAuthenticated: false });
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
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },
}));
