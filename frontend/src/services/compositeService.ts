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
  return `data:image/png;base64,${b64}`;
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
    p_low?: number;
    p_high?: number;
    gamma?: number;
    brightness?: number;
    contrast?: number;
  }): Promise<CompositeResult> {
    const { data } = await api.post<CompositeResult>('/analytics/composite', {
      stretch: 'percentile',
      p_low: 2,
      p_high: 98,
      gamma: 1,
      brightness: 1,
      contrast: 1,
      ...payload,
    });
    return data;
  },

  async stretch(payload: {
    scene_id?: string;
    bbox?: number[];
    p_low?: number;
    p_high?: number;
    gamma?: number;
    brightness?: number;
    contrast?: number;
  }): Promise<StretchResult> {
    const { data } = await api.post<StretchResult>('/analytics/stretch', payload);
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
};
