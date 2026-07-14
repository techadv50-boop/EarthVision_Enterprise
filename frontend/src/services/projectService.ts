import { api } from './api';

export interface Project {
  id: string;
  name: string;
  description?: string | null;
  status: string;
  owner_id: string;
  aoi_geojson?: GeoJSON.Geometry | null;
  center_lon?: number | null;
  center_lat?: number | null;
  zoom?: number | null;
  tags?: string[] | null;
  created_at: string;
  updated_at: string;
}

export const projectService = {
  async list(page = 1) {
    const { data } = await api.get('/projects', { params: { page } });
    return data as { items: Project[]; total: number };
  },

  async create(payload: Partial<Project> & { name: string }) {
    const { data } = await api.post<Project>('/projects', payload);
    return data;
  },

  async update(id: string, payload: Partial<Project>) {
    const { data } = await api.patch<Project>(`/projects/${id}`, payload);
    return data;
  },

  async remove(id: string) {
    await api.delete(`/projects/${id}`);
  },
};
