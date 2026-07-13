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
      { features, format, filename: 'earthvision-export' },
      { responseType: 'blob' },
    );
    return response.data as Blob;
  },
};
