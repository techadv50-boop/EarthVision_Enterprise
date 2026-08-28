import { api } from './api';
import type { LegendInfo } from './analyticsService';
import { toOverlayDataUrl } from '../utils/overlayDataUrl';

export interface DetectionResult {
  task: string;
  bounds: number[];
  overlay_base64?: string | null;
  geojson: GeoJSON.FeatureCollection;
  count: number;
  legend?: LegendInfo | null;
  message: string;
  formula?: string;
  shapefile_ready?: boolean;
  geometry_types?: string[];
}

function toDataUrl(b64: string): string {
  return toOverlayDataUrl(b64);
}

function downloadBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(href);
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
    const { data } = await api.post<DetectionResult>('/detection/run', {
      confidence_min: 0.45,
      ...payload,
    });
    return data;
  },

  async downloadShapefile(
    geojson: GeoJSON.FeatureCollection,
    filename = 'ship_detection',
  ) {
    const response = await api.post(
      '/gis/export/shapefile',
      { features: geojson, filename },
      { responseType: 'blob', timeout: 120000 },
    );
    downloadBlob(response.data as Blob, `${filename}.zip`);
  },
};
