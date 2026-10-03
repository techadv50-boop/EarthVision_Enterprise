import { create } from 'zustand';
import { authApi } from '@/services/api';

export const SERVICES = [
  { id: 'citation', label: 'Citation project', hint: 'Journals assigned to this person, archive citations, and new manuscripts' },
  { id: 'review', label: 'Article review', hint: 'Reference check and English checking' },
  { id: 'authors', label: 'Author database', hint: 'Under process and published records' },
  { id: 'galley', label: 'Galley composition', hint: 'Journal shelf and Word proofs' },
] as const;

export const REVIEW_BRANCHES = [
  { id: 'references', label: 'Reference check' },
  { id: 'language', label: 'English checking' },
] as const;

export const AUTHOR_WINGS = [
  { id: 'in_process', label: 'Under process' },
  { id: 'published', label: 'Published' },
] as const;

export type ServiceId = (typeof SERVICES)[number]['id'];
export type ReviewBranchId = (typeof REVIEW_BRANCHES)[number]['id'];
export type AuthorWingId = (typeof AUTHOR_WINGS)[number]['id'];

export const ADMIN_DESKS = SERVICES.map((service) => ({
  id: service.id,
  label: service.label,
  hint: service.hint,
}));
export type AdminDeskId = ServiceId;

export interface ServicePrivileges {
  services: string[];
  review_branches: string[];
  author_wings: string[];
  all_journals: boolean;
}

export function emptyPrivileges(): ServicePrivileges {
  return { services: [], review_branches: [], author_wings: [], all_journals: false };
}

export function fullPrivileges(): ServicePrivileges {
  return {
    services: SERVICES.map((s) => s.id),
    review_branches: REVIEW_BRANCHES.map((b) => b.id),
    author_wings: AUTHOR_WINGS.map((w) => w.id),
    all_journals: true,
  };
}

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
  privileges?: ServicePrivileges;
  can_manage_users?: boolean;
  assigned_journal_ids?: number[];
}

function privilegesOf(user: User | null | undefined): ServicePrivileges {
  if (!user) return emptyPrivileges();
  if (user.is_superuser || (user.roles || []).includes('admin')) return fullPrivileges();
  if (user.privileges) {
    return {
      services: user.privileges.services || [],
      review_branches: user.privileges.review_branches || [],
      author_wings: user.privileges.author_wings || [],
      all_journals: Boolean(user.privileges.all_journals),
    };
  }
  const desks = user.desks || [];
  const fromRoles = SERVICES.map((s) => s.id).filter((id) => (user.roles || []).includes(`admin_${id}`));
  const services = SERVICES.map((s) => s.id).filter((id) => desks.includes(id) || fromRoles.includes(id));
  if (!services.includes('citation') && (user.assigned_journal_ids || []).length) {
    services.push('citation');
  }
  return {
    services,
    review_branches: services.includes('review') ? REVIEW_BRANCHES.map((b) => b.id) : [],
    author_wings: services.includes('authors') ? AUTHOR_WINGS.map((w) => w.id) : [],
    all_journals: services.includes('citation') && desks.includes('citation'),
  };
}

function desksFromRoles(user: User | null | undefined): AdminDeskId[] {
  return privilegesOf(user).services.filter((id): id is AdminDeskId =>
    SERVICES.some((service) => service.id === id),
  );
}

export function isFullAdmin(user: User | null | undefined): boolean {
  if (!user) return false;
  return Boolean(user.is_superuser || (user.roles || []).includes('admin'));
}

export function canManageUsers(user: User | null | undefined): boolean {
  if (!user) return false;
  if (isFullAdmin(user) || user.can_manage_users) return true;
  return (user.roles || []).includes('admin_users') || (user.desks || []).includes('users');
}

export function hasService(user: User | null | undefined, service: ServiceId): boolean {
  return privilegesOf(user).services.includes(service);
}

export function hasReviewBranch(user: User | null | undefined, branch: ReviewBranchId): boolean {
  return privilegesOf(user).review_branches.includes(branch);
}

export function hasAuthorWing(user: User | null | undefined, wing: AuthorWingId): boolean {
  return privilegesOf(user).author_wings.includes(wing);
}

export function hasDesk(user: User | null | undefined, desk: AdminDeskId | 'users'): boolean {
  if (desk === 'users') return canManageUsers(user);
  return hasService(user, desk);
}

export function hasAnyDesk(user: User | null | undefined): boolean {
  return canManageUsers(user) || desksFromRoles(user).length > 0;
}

export function deskList(user: User | null | undefined): AdminDeskId[] {
  return desksFromRoles(user);
}

export function isCitationAdmin(user: User | null | undefined): boolean {
  return isFullAdmin(user);
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
