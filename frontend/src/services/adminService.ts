import { api } from './api';
import type { User } from './authService';

export type ClientRole = User['role'];

export interface AdminUser extends User {
  bio?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface UserListResponse {
  items: AdminUser[];
  total: number;
  page: number;
  page_size: number;
}

export interface CreateClientPayload {
  email: string;
  password: string;
  full_name: string;
  role: ClientRole;
  organization?: string;
  /** null = all toolboxes; list = only those */
  allowed_tools: string[] | null;
}

export interface UpdateClientPayload {
  full_name?: string;
  organization?: string | null;
  role?: ClientRole;
  is_active?: boolean;
  allowed_tools?: string[] | null;
}

export const adminService = {
  async listUsers(page = 1, pageSize = 50): Promise<UserListResponse> {
    const { data } = await api.get<UserListResponse>('/users', {
      params: { page, page_size: pageSize },
    });
    return data;
  },

  async createUser(payload: CreateClientPayload): Promise<AdminUser> {
    const { data } = await api.post<AdminUser>('/users', payload);
    return data;
  },

  async updateUser(userId: string, payload: UpdateClientPayload): Promise<AdminUser> {
    const { data } = await api.patch<AdminUser>(`/users/${userId}`, payload);
    return data;
  },
};
