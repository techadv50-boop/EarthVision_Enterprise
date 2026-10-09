import { api } from './api';

export interface SatellitePublic {
  id: string;
  name: string;
  label: string;
  collection_id: string;
  enabled: boolean;
  is_builtin: boolean;
  /** Enables AI / Change / Maritime / Air (high-res imagery only). */
  is_high_resolution: boolean;
  sort_order: number;
}

export interface SatelliteAdmin extends SatellitePublic {
  api_base_url?: string | null;
  token_url?: string | null;
  client_id?: string | null;
  auth_username?: string | null;
  has_password?: boolean;
  notes?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface SatelliteCreatePayload {
  name: string;
  label: string;
  collection_id: string;
  api_base_url?: string;
  token_url?: string;
  client_id?: string;
  auth_username?: string;
  auth_password?: string;
  notes?: string;
  enabled?: boolean;
  is_high_resolution?: boolean;
  sort_order?: number;
}

export interface SatelliteUpdatePayload {
  label?: string;
  collection_id?: string;
  api_base_url?: string | null;
  token_url?: string | null;
  client_id?: string | null;
  auth_username?: string | null;
  auth_password?: string;
  notes?: string | null;
  enabled?: boolean;
  is_high_resolution?: boolean;
  sort_order?: number;
}

export const satelliteService = {
  /** Enabled satellites for all authenticated clients. */
  async listEnabled(): Promise<SatellitePublic[]> {
    const { data } = await api.get<{ total: number; items: SatellitePublic[] }>('/satellites');
    return data.items;
  },

  async listAdmin(): Promise<SatelliteAdmin[]> {
    const { data } = await api.get<{ total: number; items: SatelliteAdmin[] }>(
      '/satellites/admin',
    );
    return data.items;
  },

  async create(payload: SatelliteCreatePayload): Promise<SatelliteAdmin> {
    const { data } = await api.post<SatelliteAdmin>('/satellites/admin', payload);
    return data;
  },

  async update(id: string, payload: SatelliteUpdatePayload): Promise<SatelliteAdmin> {
    const { data } = await api.patch<SatelliteAdmin>(`/satellites/admin/${id}`, payload);
    return data;
  },

  async remove(id: string): Promise<void> {
    await api.delete(`/satellites/admin/${id}`);
  },
};
