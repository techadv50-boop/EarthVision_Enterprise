import { api } from './api';
import type { LegendInfo } from './analyticsService';

export type TerrainProduct =
  | 'dem'
  | 'slope'
  | 'aspect'
  | 'hillshade'
  | 'contour'
  | 'watershed'
  | 'viewshed'
  | 'profile'
  | 'line_of_sight'
  | 'flow_direction'
  | 'flow_accumulation'
  | 'ruggedness'
  | 'cut_fill';

export interface TerrainResult {
  product: TerrainProduct;
  bounds: number[];
  overlay_base64?: string | null;
  legend?: LegendInfo | null;
  geojson?: GeoJSON.FeatureCollection | null;
  dem_grid?: number[][] | null;
  dem_stats?: Record<string, number> | null;
  drape_base64?: string | null;
  profile?: Array<Record<string, number>> | null;
  line_of_sight?: {
    visible: boolean;
    min_clearance_m: number;
    observer: number[];
    target: number[];
  } | null;
  formula?: string | null;
  message?: string | null;
}

export interface BufferResult {
  geometry: GeoJSON.Geometry;
  distance_meters: number;
  area_sq_meters?: number | null;
  bounds: number[];
}

function toDataUrl(b64: string): string {
  return `data:image/png;base64,${b64}`;
}

export const terrainService = {
  toDataUrl,

  async listProducts() {
    const { data } = await api.get('/terrain/products');
    return data as Array<{ id: TerrainProduct; name: string; group: string; legend?: boolean }>;
  },

  async compute(payload: {
    product: TerrainProduct;
    bbox?: number[];
    aoi?: GeoJSON.Geometry | null;
    size?: number;
    contour_interval?: number;
    observer?: [number, number];
    target?: [number, number];
    observer_height_m?: number;
    target_height_m?: number;
    profile_line?: GeoJSON.Geometry;
    azimuth_deg?: number;
    altitude_deg?: number;
    scene_id?: string;
  }): Promise<TerrainResult> {
    const { data } = await api.post<TerrainResult>('/terrain/compute', payload);
    return data;
  },
};

export const gisBufferService = {
  async buffer(geometry: GeoJSON.Geometry, distance_meters: number): Promise<BufferResult> {
    const { data } = await api.post<BufferResult>('/gis/buffer', {
      geometry,
      distance_meters,
    });
    return data;
  },
};
