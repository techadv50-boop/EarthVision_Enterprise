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
  class_id?: number;
}

export interface ClassificationResult {
  scene_id: string;
  algorithm: string;
  classes: ClassAreaStat[];
  total_area_km2: number;
  valid_pixels: number;
  bounds: number[];
  overlay_base64: string;
  /** Single-band class-id PNG for recoloring after classification */
  class_map_base64?: string | null;
  legend: LegendInfo;
  formula: string;
  message: string;
  agreement_percent?: number | null;
  metadata?: Record<string, unknown> | null;
}

export type ClassCount = 3 | 4 | 5 | 6 | 7 | 8;

/** Default styles for the full 8-class taxonomy. */
export const DEFAULT_CLASS_STYLES: ClassStyle[] = [
  { name: 'snow', label: 'Snow', color: '#F8FAFC', class_id: 0 },
  { name: 'bare_soil', label: 'Bare Soil', color: '#F0C040', class_id: 1 },
  { name: 'built_up', label: 'Built-up', color: '#E11D48', class_id: 2 },
  { name: 'vegetation', label: 'Vegetation', color: '#16A34A', class_id: 3 },
  { name: 'water', label: 'Water', color: '#1D4ED8', class_id: 4 },
  { name: 'roads', label: 'Roads', color: '#111827', class_id: 5 },
  { name: 'cropland', label: 'Cropland', color: '#84CC16', class_id: 6 },
  { name: 'wetland', label: 'Wetland', color: '#0891B2', class_id: 7 },
];

/** Which classes are active for each n_classes preset (matches backend). */
export const CLASS_PRESETS: Record<ClassCount, string[]> = {
  3: ['vegetation', 'bare_soil', 'water'],
  4: ['vegetation', 'bare_soil', 'built_up', 'water'],
  5: ['bare_soil', 'built_up', 'vegetation', 'water', 'roads'],
  6: ['snow', 'bare_soil', 'built_up', 'vegetation', 'water', 'roads'],
  7: ['snow', 'bare_soil', 'built_up', 'vegetation', 'water', 'roads', 'cropland'],
  8: [
    'snow',
    'bare_soil',
    'built_up',
    'vegetation',
    'water',
    'roads',
    'cropland',
    'wetland',
  ],
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
      class_id: found?.class_id ?? fallback.class_id,
    };
  });
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
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

  /** Server-side recolor (keeps classification; only palette changes). */
  async recolor(payload: {
    class_map_base64: string;
    classes: ClassStyle[];
  }): Promise<{ overlay_base64: string; classes: ClassStyle[]; legend: LegendInfo; message: string }> {
    const { data } = await api.post('/analytics/classify/recolor', payload);
    return data as {
      overlay_base64: string;
      classes: ClassStyle[];
      legend: LegendInfo;
      message: string;
    };
  },

  /**
   * Client-side recolor of a class-id PNG → opaque RGBA data URL.
   * Used for instant preview after the user changes colors.
   */
  async recolorLocal(
    classMapBase64: string,
    classes: Array<{ class_id: number; color: string }>,
  ): Promise<string> {
    const src = await createImageBitmap(
      await (await fetch(this.toDataUrl(classMapBase64))).blob(),
    );
    const canvas = document.createElement('canvas');
    canvas.width = src.width;
    canvas.height = src.height;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) throw new Error('Canvas unavailable');
    ctx.drawImage(src, 0, 0);
    const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const data = image.data;
    // Source was drawn as grayscale L→RGBA where R=G=B=class_id
    const lut = new Map<number, [number, number, number]>();
    for (const c of classes) {
      lut.set(c.class_id, hexToRgb(c.color));
    }
    for (let i = 0; i < data.length; i += 4) {
      const cid = data[i]; // R channel holds class id for mode-L PNG
      if (cid === 255) {
        data[i + 3] = 0;
        continue;
      }
      const rgb = lut.get(cid);
      if (!rgb) {
        data[i + 3] = 0;
        continue;
      }
      data[i] = rgb[0];
      data[i + 1] = rgb[1];
      data[i + 2] = rgb[2];
      data[i + 3] = 255;
    }
    ctx.putImageData(image, 0, 0);
    const dataUrl = canvas.toDataURL('image/png');
    // strip prefix for storage consistency with overlay_base64 consumers when needed
    return dataUrl;
  },

  downloadPngFromBase64(b64: string, filename: string) {
    const a = document.createElement('a');
    a.href = b64.startsWith('data:') ? b64 : this.toDataUrl(b64);
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
    const overlay = result.overlay_base64.includes(',')
      ? result.overlay_base64.split(',')[1]
      : result.overlay_base64;
    const { data } = await api.post(
      '/analytics/export/geotiff',
      {
        bounds: result.bounds,
        filename: `lulc${n}_${sceneId}.tif`,
        overlay_base64: overlay,
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
