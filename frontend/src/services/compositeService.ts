import { api } from './api';
import type { LegendInfo } from './analyticsService';
import { INTERACTIVE_PREVIEW_SIZE, toOverlayDataUrl } from '../utils/overlayDataUrl';

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
  landsat8?: string;
  landsat9?: string;
  landsat7?: string;
  modis?: string;
  bands: { R: string; G: string; B: string };
  applicable?: string[];
  enabled?: boolean;
  disabled_reason?: string | null;
  active_codes?: string | null;
  active_family?: string | null;
  satellite_formulas?: Record<string, { codes: string; formula: string }>;
}

export interface IndexThematicInfo {
  id: string;
  formula: string;
  bands: string;
  thematic_rgb: string;
  colormap: string;
  applicable?: string[];
  enabled?: boolean;
  disabled_reason?: string | null;
  satellite_bands?: Record<string, string>;
}

export interface CompositeResult {
  preset: string;
  label: string;
  bands: { R: string; G: string; B: string };
  band_keys: { R: string; G: string; B: string };
  formula: string;
  bounds: number[];
  overlay_base64: string;
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
  overlay_base64: string;
  histogram: CompositeResult['histogram'];
  p_low: number;
  p_high: number;
  gamma: number;
  brightness: number;
  contrast: number;
  message: string;
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

export const compositeService = {
  toDataUrl,

  async listPresets(opts?: { collection?: string | null }): Promise<CompositePresetInfo[]> {
    const { data } = await api.get('/analytics/composites', {
      params: opts?.collection ? { collection: opts.collection } : undefined,
    });
    return data;
  },

  async listIndexThematic(opts?: {
    collection?: string | null;
  }): Promise<IndexThematicInfo[]> {
    const { data } = await api.get('/analytics/index-thematic', {
      params: opts?.collection ? { collection: opts.collection } : undefined,
    });
    return data;
  },

  async render(payload: {
    preset: CompositePreset;
    scene_id?: string;
    collection?: string;
    bbox?: number[];
    size?: number;
    p_low?: number;
    p_high?: number;
    gamma?: number;
    brightness?: number;
    contrast?: number;
  }): Promise<CompositeResult> {
    const { data } = await api.post<CompositeResult>('/analytics/composite', {
      stretch: 'percentile',
      size: INTERACTIVE_PREVIEW_SIZE,
      p_low: 2,
      p_high: 98,
      gamma: 1.35,
      brightness: 1.0,
      contrast: 1.05,
      ...payload,
    });
    return data;
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
    const { data } = await api.post<StretchResult>('/analytics/stretch', {
      size: INTERACTIVE_PREVIEW_SIZE,
      ...payload,
    });
    return data;
  },

  async downloadPngFromBase64(b64: string, filename: string) {
    const res = await fetch(toDataUrl(b64));
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

  async downloadGeotiffBlob(blob: Blob, filename: string) {
    downloadBlob(blob, filename.endsWith('.tif') ? filename : `${filename}.tif`);
  },

  /** Universal GeoTIFF export from an already-rendered overlay (or regenerate). */
  async downloadGeotiff(payload: {
    bounds: number[];
    filename: string;
    overlay_base64?: string | null;
    dem_grid?: number[][] | null;
    procedure?: 'overlay' | 'composite' | 'index' | 'stretch' | 'change';
    scene_id?: string;
    before_scene_id?: string;
    after_scene_id?: string;
    preset?: string;
    index?: string;
    colormap?: string | null;
    p_low?: number;
    p_high?: number;
  }): Promise<void> {
    const { data, headers } = await api.post<Blob>('/analytics/export/geotiff', payload, {
      responseType: 'blob',
      timeout: 180000,
    });
    const disposition = String(headers['content-disposition'] || '');
    const match = /filename="?([^";]+)"?/i.exec(disposition);
    const filename = match?.[1] || payload.filename || 'sateye.tif';
    downloadBlob(data as Blob, filename);
  },

  async downloadCompositeGeotiff(
    preset: string,
    sceneId: string | undefined,
    bbox: number[],
  ) {
    const [west, south, east, north] = bbox;
    const { data, headers } = await api.get<Blob>('/analytics/export/composite.tif', {
      params: { preset, scene_id: sceneId, west, south, east, north },
      responseType: 'blob',
      timeout: 180000,
    });
    const disposition = String(headers['content-disposition'] || '');
    const match = /filename="?([^";]+)"?/i.exec(disposition);
    downloadBlob(
      data as Blob,
      match?.[1] || `${preset}_${sceneId || 'aoi'}.tif`,
    );
  },

  async downloadIndexGeotiff(
    index: string,
    sceneId: string,
    bbox: number[],
    colormap?: string | null,
  ) {
    const [west, south, east, north] = bbox;
    const { data, headers } = await api.get<Blob>('/analytics/export/index.tif', {
      params: { index, scene_id: sceneId, west, south, east, north, colormap },
      responseType: 'blob',
      timeout: 180000,
    });
    const disposition = String(headers['content-disposition'] || '');
    const match = /filename="?([^";]+)"?/i.exec(disposition);
    downloadBlob(data as Blob, match?.[1] || `${index}_${sceneId}.tif`);
  },

  async downloadStretchGeotiff(
    sceneId: string | undefined,
    bbox: number[],
    params?: { p_low?: number; p_high?: number },
  ) {
    const [west, south, east, north] = bbox;
    const { data, headers } = await api.get<Blob>('/analytics/export/stretch.tif', {
      params: {
        scene_id: sceneId,
        west,
        south,
        east,
        north,
        p_low: params?.p_low ?? 2,
        p_high: params?.p_high ?? 98,
      },
      responseType: 'blob',
      timeout: 180000,
    });
    const disposition = String(headers['content-disposition'] || '');
    const match = /filename="?([^";]+)"?/i.exec(disposition);
    downloadBlob(data as Blob, match?.[1] || `stretch_${sceneId || 'aoi'}.tif`);
  },

  /** Resolve overlay URL / data-URL into base64 for GeoTIFF packaging. */
  async overlayUrlToBase64(url: string): Promise<string> {
    if (url.startsWith('data:')) {
      const parts = url.split(',', 2);
      if (parts.length === 2) return parts[1];
    }
    const res = await fetch(url);
    const blob = await res.blob();
    const buf = await blob.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let binary = '';
    for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
  },
};
