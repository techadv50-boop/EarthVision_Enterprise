import { api } from './api';

export type IndexName = 'NDVI' | 'NDWI' | 'NDBI' | 'SAVI' | 'BSI' | 'LST';

export interface IndexResult {
  index: IndexName;
  mean: number;
  std: number;
  min: number;
  max: number;
  median: number;
  percentile_25: number;
  percentile_75: number;
  valid_pixels: number;
  histogram: { counts: number[]; edges: number[] };
  preview_base64?: string | null;
  output_path?: string | null;
}

export const analyticsService = {
  async listIndices() {
    const { data } = await api.get('/analytics/indices');
    return data as Array<{ id: string; name: string; formula: string }>;
  },

  async computeIndex(index: IndexName, sceneId?: string): Promise<IndexResult> {
    const { data } = await api.post<IndexResult>('/analytics/index', {
      index,
      scene_id: sceneId,
    });
    return data;
  },

  async timeSeries(index: IndexName, sceneIds: string[]) {
    const { data } = await api.post('/analytics/timeseries', {
      index,
      scene_ids: sceneIds,
    });
    return data;
  },

  async inspectPixel(longitude: number, latitude: number, sceneId?: string) {
    const { data } = await api.post('/analytics/pixel', {
      longitude,
      latitude,
      scene_id: sceneId,
    });
    return data;
  },
};
