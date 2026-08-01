import { api } from './api';
import type { LegendInfo } from './analyticsService';

export interface ClassAreaStat {
  class_id: number;
  name: string;
  label: string;
  color: string;
  pixels: number;
  percent: number;
  area_km2: number;
}

export interface ClassificationResult {
  scene_id: string;
  algorithm: string;
  classes: ClassAreaStat[];
  total_area_km2: number;
  valid_pixels: number;
  bounds: number[];
  overlay_base64: string;
  legend: LegendInfo;
  formula: string;
  message: string;
  agreement_percent?: number | null;
  metadata?: Record<string, unknown> | null;
}

export const classificationService = {
  toDataUrl(b64: string): string {
    return `data:image/png;base64,${b64}`;
  },

  async classify(payload: {
    scene_id: string;
    bbox?: number[];
    size?: number;
  }): Promise<ClassificationResult> {
    const { data } = await api.post<ClassificationResult>('/analytics/classify', {
      n_classes: 6,
      size: 1536,
      ...payload,
    });
    return data;
  },

  downloadPngFromBase64(b64: string, filename: string) {
    const a = document.createElement('a');
    a.href = this.toDataUrl(b64);
    a.download = filename;
    a.click();
  },

  downloadCsvText(text: string, filename: string) {
    const blob = new Blob([text], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  },

  buildResultsCsv(result: ClassificationResult): string {
    const rows = [
      'class_id,name,label,color,pixels,percent,area_km2',
      ...result.classes.map(
        (c) =>
          `${c.class_id},${c.name},"${c.label}",${c.color},${c.pixels},${c.percent},${c.area_km2}`,
      ),
      `,,,TOTAL,,,${result.total_area_km2}`,
      `algorithm,,,${result.algorithm},,,`,
      `agreement_percent,,,${result.agreement_percent ?? ''},,,`,
      `valid_pixels,,,${result.valid_pixels},,,`,
      `bounds,,,${result.bounds.join(' ')},,,`,
    ];
    return rows.join('\n') + '\n';
  },

  async downloadGeotiff(result: ClassificationResult, sceneId: string) {
    const { data } = await api.post(
      '/analytics/export/geotiff',
      {
        bounds: result.bounds,
        filename: `lulc6_${sceneId}.tif`,
        overlay_base64: result.overlay_base64,
        procedure: 'overlay',
        scene_id: sceneId,
      },
      { responseType: 'blob' },
    );
    const url = URL.createObjectURL(data as Blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `lulc6_${sceneId}.tif`;
    a.click();
    URL.revokeObjectURL(url);
  },
};
