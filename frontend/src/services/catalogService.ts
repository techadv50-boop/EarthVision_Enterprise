import { api } from './api';

/** Built-in names plus any admin-registered satellite collection ids. */
export type CollectionName = string

export interface CatalogSearchRequest {
  collections: CollectionName[];
  start_date?: string | null;
  end_date?: string | null;
  cloud_cover_max?: number | null;
  bbox?: number[] | null;
  aoi?: { type: string; coordinates: unknown } | null;
  max_results?: number;
  product_type?: string | null;
}

export interface SceneSummary {
  id: string;
  name: string;
  collection: string;
  platform: string;
  sensing_time?: string | null;
  cloud_cover?: number | null;
  footprint?: GeoJSON.Geometry | null;
  center?: number[] | null;
  thumbnail_url?: string | null;
  size_bytes?: number | null;
  product_type?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface CatalogSearchResponse {
  total: number;
  items: SceneSummary[];
  query: Record<string, unknown>;
}

export const catalogService = {
  async search(request: CatalogSearchRequest): Promise<CatalogSearchResponse> {
    const { data } = await api.post<CatalogSearchResponse>('/catalog/search', request);
    return data;
  },

  async authStatus(): Promise<{ configured: boolean; has_token: boolean; expires_at: string | null }> {
    const { data } = await api.get('/catalog/auth-status');
    return data;
  },

  async download(sceneId: string, collection: string) {
    const { data } = await api.post('/catalog/download', {
      scene_id: sceneId,
      collection,
    });
    return data;
  },

  async listScenes(collection?: string) {
    const { data } = await api.get('/catalog/scenes', { params: { collection } });
    return data;
  },

  previewUrl(sceneId: string): string {
    const base = import.meta.env.VITE_API_URL || '/api/v1';
    return `${base}/catalog/scenes/${sceneId}/preview`;
  },
};
