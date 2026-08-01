import { api } from './api';
import axios from 'axios';

export type CollectionName =
  | 'SENTINEL-1'
  | 'SENTINEL-2'
  | 'LANDSAT-8'
  | 'LANDSAT-9'
  | 'MODIS';

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

export interface DownloadBandInfo {
  id: string;
  label: string;
  code: string;
  filename: string;
  extension: string;
  format: string;
  media_type?: string;
  group?: string;
}

export interface SceneBandsResponse {
  scene_id: string;
  collection?: string;
  stac_id?: string;
  bounds?: number[];
  bands: DownloadBandInfo[];
  default_bands: string[];
  formats: string[];
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

  /** List selectable spectral / SAR bands for a scene download. */
  async listBands(
    scene: SceneSummary,
    opts?: { bbox?: number[] },
  ): Promise<SceneBandsResponse> {
    const params: Record<string, string | number> = {
      collection: scene.collection,
    };
    if (scene.sensing_time) params.sensing_time = scene.sensing_time;
    if (scene.cloud_cover != null) params.cloud_cover = scene.cloud_cover;
    if (opts?.bbox && opts.bbox.length === 4) {
      const [west, south, east, north] = opts.bbox;
      params.west = west;
      params.south = south;
      params.east = east;
      params.north = north;
    }
    const { data } = await api.get<SceneBandsResponse>(
      `/catalog/scenes/${encodeURIComponent(scene.id)}/bands`,
      { params, timeout: 120000 },
    );
    return data;
  },

  /** Download user-selected bands as a multi-band GeoTIFF. */
  async downloadBands(
    scene: SceneSummary,
    bands: string[],
    opts?: { bbox?: number[]; size?: number },
  ): Promise<void> {
    if (!bands.length) {
      throw new Error('Select at least one band to download');
    }
    try {
      const { data, headers } = await api.post<Blob>(
        `/catalog/scenes/${encodeURIComponent(scene.id)}/bands/download`,
        {
          collection: scene.collection,
          bbox: opts?.bbox,
          footprint: scene.footprint ?? undefined,
          sensing_time: scene.sensing_time ?? undefined,
          cloud_cover: scene.cloud_cover ?? undefined,
          bands,
          size: opts?.size ?? 512,
        },
        {
          responseType: 'blob',
          timeout: 300000,
        },
      );
      const disposition = String(headers['content-disposition'] || '');
      const match = /filename="?([^";]+)"?/i.exec(disposition);
      const safeName = (scene.name || scene.id).replace(/[^\w.-]+/g, '_').slice(0, 80);
      const bandTag = bands.join('-').slice(0, 40);
      const filename =
        match?.[1] || `${scene.collection}_${safeName}_${bandTag}.tif`;
      const href = URL.createObjectURL(data);
      const a = document.createElement('a');
      a.href = href;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(href);
    } catch (err) {
      // Axios blob errors often wrap JSON detail in a Blob body
      if (axios.isAxiosError(err) && err.response?.data instanceof Blob) {
        try {
          const text = await err.response.data.text();
          const parsed = JSON.parse(text) as { detail?: unknown };
          if (typeof parsed.detail === 'string') {
            throw new Error(parsed.detail);
          }
        } catch (inner) {
          if (inner instanceof Error && inner.message && !inner.message.startsWith('{')) {
            throw inner;
          }
        }
      }
      throw err;
    }
  },

  /** Download the scene imagery PNG (true-color / SAR grayscale). */
  async downloadImage(
    scene: SceneSummary,
    opts?: { bbox?: number[]; size?: number },
  ): Promise<void> {
    const params: Record<string, string | number> = {
      size: opts?.size ?? 768,
      collection: scene.collection,
    };
    if (opts?.bbox && opts.bbox.length === 4) {
      const [west, south, east, north] = opts.bbox;
      params.west = west;
      params.south = south;
      params.east = east;
      params.north = north;
    }
    const { data, headers } = await api.get<Blob>(
      `/catalog/scenes/${encodeURIComponent(scene.id)}/overlay.png`,
      {
        params,
        responseType: 'blob',
        timeout: 180000,
      },
    );
    const disposition = String(headers['content-disposition'] || '');
    const match = /filename="?([^";]+)"?/i.exec(disposition);
    const safeName = (scene.name || scene.id).replace(/[^\w.-]+/g, '_').slice(0, 80);
    const filename = match?.[1] || `${scene.collection}_${safeName}.png`;
    const href = URL.createObjectURL(data);
    const a = document.createElement('a');
    a.href = href;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(href);
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
