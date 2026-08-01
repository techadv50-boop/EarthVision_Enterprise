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

export interface ClassStyle {
  name: string;
  label: string;
  color: string;
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

export type ClassCount = 3 | 4 | 5 | 6;

/** Default styles for the full 6-class taxonomy. */
export const DEFAULT_CLASS_STYLES: ClassStyle[] = [
  { name: 'snow', label: 'Snow', color: '#F8FAFC' },
  { name: 'bare_soil', label: 'Bare Soil', color: '#F0C040' },
  { name: 'built_up', label: 'Built-up', color: '#E11D48' },
  { name: 'vegetation', label: 'Vegetation', color: '#16A34A' },
  { name: 'water', label: 'Water', color: '#1D4ED8' },
  { name: 'roads', label: 'Roads', color: '#111827' },
];

/** Which classes are active for each n_classes preset (matches backend). */
export const CLASS_PRESETS: Record<ClassCount, string[]> = {
  3: ['vegetation', 'bare_soil', 'water'],
  4: ['vegetation', 'bare_soil', 'built_up', 'water'],
  5: ['bare_soil', 'built_up', 'vegetation', 'water', 'roads'],
  6: ['snow', 'bare_soil', 'built_up', 'vegetation', 'water', 'roads'],
};

export function stylesForCount(
  n: ClassCount,
  allStyles: ClassStyle[] = DEFAULT_CLASS_STYLES,
): ClassStyle[] {
  const names = CLASS_PRESETS[n];
  return names.map((name) => {
    const found = allStyles.find((s) => s.name === name);
    const fallback = DEFAULT_CLASS_STYLES.find((s) => s.name === name)!;
    return {
      name,
      label: found?.label ?? fallback.label,
      color: found?.color ?? fallback.color,
    };
  });
}

export const classificationService = {
  toDataUrl(b64: string): string {
    return `data:image/png;base64,${b64}`;
  },

  async classify(payload: {
    scene_id: string;
    bbox?: number[];
    size?: number;
    n_classes?: ClassCount;
    class_styles?: ClassStyle[];
  }): Promise<ClassificationResult> {
    const n = (payload.n_classes ?? 6) as ClassCount;
    const { data } = await api.post<ClassificationResult>('/analytics/classify', {
      scene_id: payload.scene_id,
      bbox: payload.bbox,
      size: payload.size ?? 1792,
      n_classes: n,
      class_styles: payload.class_styles ?? stylesForCount(n),
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
    const n =
      (result.metadata?.n_classes as number | undefined) ??
      result.classes.length ??
      6;
    const { data } = await api.post(
      '/analytics/export/geotiff',
      {
        bounds: result.bounds,
        filename: `lulc${n}_${sceneId}.tif`,
        overlay_base64: result.overlay_base64,
        procedure: 'overlay',
        scene_id: sceneId,
      },
      { responseType: 'blob' },
    );
    const url = URL.createObjectURL(data as Blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `lulc${n}_${sceneId}.tif`;
    a.click();
    URL.revokeObjectURL(url);
  },
};
