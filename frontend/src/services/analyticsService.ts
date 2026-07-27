import { api } from './api';

export type IndexName =
  | 'NDVI'
  | 'NDWI'
  | 'NDBI'
  | 'SAVI'
  | 'BSI'
  | 'LST'
  | 'EVI'
  | 'NDMI'
  | 'NBR';

export interface LegendInfo {
  min: number;
  max: number;
  unit: string;
  label: string;
  formula: string;
  stops: Array<{ value: number; color: string }>;
  colormap?: string | null;
}

export type ColormapName =
  | 'rdylgn'
  | 'blues'
  | 'ylorbr'
  | 'soil'
  | 'thermal'
  | 'rdbu'
  | 'viridis'
  | 'magma'
  | 'turbo'
  | 'gray'
  | 'brbg';

export interface ColormapInfo {
  id: ColormapName;
  label: string;
  stops: Array<{ value: number; color: string }>;
}

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
  overlay_base64?: string | null;
  overlay_url?: string | null;
  bounds?: number[] | null;
  legend?: LegendInfo | null;
  formula?: string | null;
  output_path?: string | null;
  colormap?: string | null;
}

export interface ChangeResult {
  index: IndexName;
  before_scene_id: string;
  after_scene_id: string;
  mean_before: number;
  mean_after: number;
  mean_difference: number;
  change_ratio: number;
  significant_pixels: number;
  overlay_base64?: string;
  overlay_url?: string | null;
  bounds: number[];
  legend: LegendInfo;
  formula: string;
}

export interface SceneOverlay {
  scene_id: string;
  overlay_base64?: string;
  bounds: number[];
  download_url?: string;
  local_path?: string;
  /** XYZ template e.g. /api/v1/catalog/scenes/{id}/tiles/{z}/{x}/{y}.png */
  tile_url?: string;
  /** Full-scene preview PNG URL for ImageOverlay (avoids huge base64 over tunnels) */
  preview_url?: string;
  source?: string;
  composite?: string;
  render_mode?: 'rgb' | 'grayscale';
  bands?: { R: string; G: string; B: string };
  label?: string;
  collection?: string;
  stac_id?: string;
  acquisition_date?: string;
  cloud_cover?: number | null;
  footprint?: GeoJSON.Polygon | null;
  thumbnail_url?: string;
}

function toDataUrl(b64: string): string {
  return `data:image/png;base64,${b64}`;
}

function resolveOverlayUrl(result: {
  overlay_url?: string | null;
  overlay_base64?: string | null;
}): string {
  if (result.overlay_url) return result.overlay_url;
  if (result.overlay_base64) return toDataUrl(result.overlay_base64);
  return '';
}

async function pollAnalyticsJob<T>(jobId: string, timeoutMs = 180000): Promise<T> {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const { data } = await api.get<{
      job_id: string;
      status: string;
      result?: T;
      error?: string;
    }>(`/analytics/jobs/${jobId}`);
    if (data.status === 'done' && data.result) return data.result;
    if (data.status === 'error') {
      throw new Error(data.error || 'Analytics job failed');
    }
    await new Promise((r) => setTimeout(r, 900));
  }
  throw new Error('Timed out waiting for analytics job');
}

export const analyticsService = {
  toDataUrl,
  resolveOverlayUrl,

  async listIndices() {
    const { data } = await api.get('/analytics/indices');
    return data as Array<{
      id: string;
      name: string;
      formula: string;
      reference?: string;
      default_colormap?: string;
    }>;
  },

  async listColormaps() {
    const { data } = await api.get('/analytics/colormaps');
    return data as ColormapInfo[];
  },

  async computeIndex(
    index: IndexName,
    sceneId?: string,
    bbox?: number[],
    colormap?: ColormapName | string | null,
  ): Promise<IndexResult> {
    const { data } = await api.post<{ job_id: string; status: string } | IndexResult>(
      '/analytics/index',
      {
        index,
        scene_id: sceneId,
        bbox,
        colormap: colormap || undefined,
      },
    );
    if (data && typeof data === 'object' && 'job_id' in data && data.job_id) {
      return pollAnalyticsJob<IndexResult>(data.job_id);
    }
    return data as IndexResult;
  },

  async changeDetection(payload: {
    before_scene_id: string;
    after_scene_id: string;
    index?: IndexName;
    bbox?: number[];
    threshold?: number;
  }): Promise<ChangeResult> {
    const { data } = await api.post<{ job_id: string; status: string } | ChangeResult>(
      '/analytics/change',
      {
        index: 'NDVI',
        threshold: 0.12,
        ...payload,
      },
    );
    if (data && typeof data === 'object' && 'job_id' in data && data.job_id) {
      return pollAnalyticsJob<ChangeResult>(data.job_id);
    }
    return data as ChangeResult;
  },

  async sceneOverlay(payload: {
    scene_id: string;
    collection?: string;
    bbox?: number[];
    footprint?: GeoJSON.Geometry | null;
    sensing_time?: string | null;
    cloud_cover?: number | null;
  }): Promise<SceneOverlay> {
    const { data } = await api.post<SceneOverlay>('/catalog/scenes/overlay', payload);
    return data;
  },

  sceneTileUrl(sceneId: string): string {
    const base = import.meta.env.VITE_API_URL || '/api/v1';
    return `${base}/catalog/scenes/${encodeURIComponent(sceneId)}/tiles/{z}/{x}/{y}.png`;
  },

  exportIndexPngUrl(index: IndexName, sceneId: string, bbox: number[]): string {
    const base = import.meta.env.VITE_API_URL || '/api/v1';
    const [west, south, east, north] = bbox;
    return `${base}/analytics/export/index.png?index=${index}&scene_id=${encodeURIComponent(sceneId)}&west=${west}&south=${south}&east=${east}&north=${north}`;
  },

  exportIndexCsvUrl(index: IndexName, sceneId: string): string {
    const base = import.meta.env.VITE_API_URL || '/api/v1';
    return `${base}/analytics/export/index.csv?index=${index}&scene_id=${encodeURIComponent(sceneId)}`;
  },

  sceneDownloadUrl(sceneId: string, bbox?: number[]): string {
    const base = import.meta.env.VITE_API_URL || '/api/v1';
    if (bbox && bbox.length === 4) {
      const [west, south, east, north] = bbox;
      return `${base}/catalog/scenes/${sceneId}/overlay.png?west=${west}&south=${south}&east=${east}&north=${north}`;
    }
    return `${base}/catalog/scenes/${sceneId}/overlay.png`;
  },
};
