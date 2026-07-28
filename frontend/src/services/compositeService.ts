import { api } from './api';
import type { LegendInfo } from './analyticsService';

export type CompositePreset =
  | 'true_color'
  | 'false_color_infrared'
  | 'false_color_agriculture'
  | 'false_color_urban'
  | 'swir_composite'
  | 'geology'
  | 'atmospheric_penetration'
  | 'land_water'
  | 'vegetation_health'
  | 'burn_severity';

export interface CompositePresetInfo {
  id: CompositePreset;
  label: string;
  formula: string;
  use: string;
  sentinel2: string;
  landsat: string;
  bands: { R: string; G: string; B: string };
}

export interface IndexThematicInfo {
  id: string;
  formula: string;
  bands: string;
  thematic_rgb: string;
  colormap: string;
}

export interface CompositeResult {
  preset: string;
  label: string;
  bands: { R: string; G: string; B: string };
  band_keys: { R: string; G: string; B: string };
  formula: string;
  bounds: number[];
  overlay_base64?: string;
  overlay_url?: string | null;
  histogram?: {
    edges: number[];
    channels: { red: number[]; green: number[]; blue: number[] };
    raw?: { edges: number[]; channels: { red: number[]; green: number[]; blue: number[] } };
  } | null;
  legend?: LegendInfo | null;
  message?: string | null;
  stretch?: string | null;
}

export interface StretchResult {
  bounds: number[];
  overlay_base64?: string;
  overlay_url?: string | null;
  histogram: CompositeResult['histogram'];
  p_low: number;
  p_high: number;
  gamma: number;
  brightness: number;
  contrast: number;
  message: string;
}

function toDataUrl(b64: string): string {
  return `data:image/png;base64,${b64}`;
}

/** Prefer tunnel-safe overlay_url; fall back to embedded base64 when present. */
function resolveOverlayUrl(result: {
  overlay_url?: string | null;
  overlay_base64?: string | null;
}): string {
  if (result.overlay_url) return result.overlay_url;
  if (result.overlay_base64) return toDataUrl(result.overlay_base64);
  return '';
}

let lastBlobUrl: string | null = null;

/**
 * Fetch overlay bytes through the API proxy and return a blob: URL.
 * Leaflet <img> loads of multi‑MB PNGs often time out on Serveo (~5s) and the
 * layer vanishes after a patchy flash — blob URLs paint atomically once fetched.
 */
async function materializeOverlayUrl(result: {
  overlay_url?: string | null;
  overlay_base64?: string | null;
}): Promise<string> {
  const url = resolveOverlayUrl(result);
  if (!url) return '';
  if (url.startsWith('data:') || url.startsWith('blob:')) return url;

  const path = url.startsWith('/api/v1/')
    ? url.slice('/api/v1'.length)
    : url.startsWith('/api/')
      ? url.slice('/api'.length)
      : url;

  const { data } = await api.get<Blob>(path, {
    responseType: 'blob',
    timeout: 90000,
    headers: { Accept: 'image/*,*/*' },
  });
  if (!(data instanceof Blob) || data.size < 32) {
    throw new Error('Overlay image was empty or truncated');
  }
  if (lastBlobUrl) {
    URL.revokeObjectURL(lastBlobUrl);
    lastBlobUrl = null;
  }
  lastBlobUrl = URL.createObjectURL(data);
  return lastBlobUrl;
}

function downloadBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(href);
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

export const compositeService = {
  toDataUrl,
  resolveOverlayUrl,
  materializeOverlayUrl,

  async listPresets(): Promise<CompositePresetInfo[]> {
    const { data } = await api.get('/analytics/composites');
    return data;
  },

  async listIndexThematic(): Promise<IndexThematicInfo[]> {
    const { data } = await api.get('/analytics/index-thematic');
    return data;
  },

  async render(payload: {
    preset: CompositePreset;
    scene_id?: string;
    bbox?: number[];
    size?: number;
    p_low?: number;
    p_high?: number;
    gamma?: number;
    brightness?: number;
    contrast?: number;
  }): Promise<CompositeResult> {
    const { data } = await api.post<{ job_id: string; status: string } | CompositeResult>(
      '/analytics/composite',
      {
        stretch: 'percentile',
        p_low: 2,
        p_high: 98,
        gamma: 1,
        brightness: 1,
        contrast: 1,
        size: 768,
        ...payload,
      },
    );
    if (data && typeof data === 'object' && 'job_id' in data && data.job_id) {
      return pollAnalyticsJob<CompositeResult>(data.job_id);
    }
    return data as CompositeResult;
  },

  async stretch(payload: {
    scene_id?: string;
    bbox?: number[];
    size?: number;
    p_low?: number;
    p_high?: number;
    gamma?: number;
    brightness?: number;
    contrast?: number;
  }): Promise<StretchResult> {
    const { data } = await api.post<{ job_id: string; status: string } | StretchResult>(
      '/analytics/stretch',
      {
        size: 768,
        ...payload,
      },
    );
    if (data && typeof data === 'object' && 'job_id' in data && data.job_id) {
      return pollAnalyticsJob<StretchResult>(data.job_id);
    }
    return data as StretchResult;
  },

  async downloadPngFromBase64(b64: string, filename: string) {
    const res = await fetch(toDataUrl(b64));
    const blob = await res.blob();
    downloadBlob(blob, filename);
  },

  async downloadOverlay(
    result: {
      overlay_url?: string | null;
      overlay_base64?: string | null;
    },
    filename: string,
  ) {
    const url = resolveOverlayUrl(result);
    if (!url) return;
    if (url.startsWith('data:')) {
      await this.downloadPngFromBase64(
        url.replace(/^data:image\/png;base64,/, ''),
        filename,
      );
      return;
    }
    const res = await fetch(url);
    const blob = await res.blob();
    downloadBlob(blob, filename);
  },

  async downloadIndexPng(index: string, sceneId: string, bbox: number[]) {
    const [west, south, east, north] = bbox;
    const { data } = await api.get('/analytics/export/index.png', {
      params: { index, scene_id: sceneId, west, south, east, north },
      responseType: 'blob',
    });
    downloadBlob(data as Blob, `${index}_${sceneId}.png`);
  },

  async downloadIndexCsv(index: string, sceneId: string) {
    const { data } = await api.get('/analytics/export/index.csv', {
      params: { index, scene_id: sceneId },
      responseType: 'blob',
    });
    downloadBlob(data as Blob, `${index}_${sceneId}_stats.csv`);
  },

  async downloadCompositePng(preset: string, sceneId: string | undefined, bbox: number[]) {
    const [west, south, east, north] = bbox;
    const { data } = await api.get('/analytics/export/composite.png', {
      params: { preset, scene_id: sceneId, west, south, east, north },
      responseType: 'blob',
    });
    downloadBlob(data as Blob, `${preset}_${sceneId || 'aoi'}.png`);
  },
};
