import { api } from './api';
import type { LegendInfo } from './analyticsService';

export interface DetectionResult {
  task: string;
  bounds: number[];
  overlay_base64?: string | null;
  geojson: GeoJSON.FeatureCollection;
  count: number;
  legend?: LegendInfo | null;
  message: string;
  formula?: string;
}

function toDataUrl(b64: string): string {
  return `data:image/png;base64,${b64}`;
}

export const detectionService = {
  toDataUrl,

  async listTasks() {
    const { data } = await api.get('/detection/tasks');
    return data as Array<{
      id: string;
      name: string;
      domain: string;
      geometry: string;
      algorithm?: string;
    }>;
  },

  async meta() {
    const { data } = await api.get('/detection/meta');
    return data as {
      tasks: string[];
      algorithms: Record<string, string>;
      formula: string;
      map_chrome: string[];
    };
  },

  async run(payload: {
    task: string;
    bbox: number[];
    scene_id?: string;
    aoi?: GeoJSON.Geometry | null;
    confidence_min?: number;
  }): Promise<DetectionResult> {
    const { data } = await api.post<DetectionResult>('/detection/run', payload);
    return data;
  },
};
