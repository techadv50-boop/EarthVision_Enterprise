import { api } from './api';

export interface GeocodeResult {
  display_name: string;
  longitude: number;
  latitude: number;
  bounding_box?: number[] | null;
  place_type?: string | null;
  importance?: number | null;
}

export const gisService = {
  async geocode(query: string, limit = 5): Promise<GeocodeResult[]> {
    const { data } = await api.post<{ results: GeocodeResult[] }>('/gis/geocode', {
      query,
      limit,
    });
    return data.results;
  },

  async reverseGeocode(longitude: number, latitude: number): Promise<GeocodeResult> {
    const { data } = await api.post<GeocodeResult>('/gis/reverse-geocode', {
      longitude,
      latitude,
    });
    return data;
  },

  async measure(geometry: GeoJSON.Geometry, unit = 'kilometers') {
    const { data } = await api.post('/gis/measure', { geometry, unit });
    return data;
  },

  async exportFeatures(features: GeoJSON.FeatureCollection, format: 'geojson' | 'kml' | 'csv') {
    const response = await api.post(
      '/gis/export',
      { features, format, filename: 'sateye-export' },
      { responseType: 'blob' },
    );
    return response.data as Blob;
  },

  async spatial(operation: string, geometries: GeoJSON.Geometry[], distance_meters?: number) {
    const { data } = await api.post('/gis/spatial', {
      operation,
      geometries,
      distance_meters,
    });
    return data as {
      operation: string;
      geometry?: GeoJSON.Geometry | null;
      geojson?: GeoJSON.FeatureCollection | null;
      count?: number;
      bounds?: number[];
      message?: string;
    };
  },

  async buffer(geometry: GeoJSON.Geometry, distance_meters: number) {
    const { data } = await api.post('/gis/buffer', { geometry, distance_meters });
    return data as {
      geometry: GeoJSON.Geometry;
      distance_meters: number;
      area_sq_meters?: number | null;
      bounds: number[];
    };
  },
};
