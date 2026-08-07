import axios from 'axios';

const API_BASE = '/api/v1';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      const refreshToken = localStorage.getItem('refresh_token');
      if (refreshToken) {
        try {
          const { data } = await axios.post(`${API_BASE}/auth/refresh`, {
            refresh_token: refreshToken,
          });
          localStorage.setItem('access_token', data.access_token);
          localStorage.setItem('refresh_token', data.refresh_token);
          original.headers.Authorization = `Bearer ${data.access_token}`;
          return api(original);
        } catch {
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
          // Offline SAT EYE has no login wall — do not redirect
        }
      }
    }
    return Promise.reject(error);
  }
);

export default api;

export const authApi = {
  login: (username: string, password: string) =>
    api.post('/auth/login', { username, password }),
  register: (data: { email: string; username: string; password: string; full_name?: string }) =>
    api.post('/auth/register', data),
  me: () => api.get('/auth/me'),
};

export const geoApi = {
  search: (q: string) => api.get('/geo/search', { params: { q } }),
  reverse: (longitude: number, latitude: number) =>
    api.get('/geo/reverse', { params: { longitude, latitude } }),
  bookmarks: {
    list: () => api.get('/geo/bookmarks'),
    create: (data: Record<string, unknown>) => api.post('/geo/bookmarks', data),
    delete: (id: number) => api.delete(`/geo/bookmarks/${id}`),
  },
  aoi: {
    list: () => api.get('/geo/aoi'),
    create: (data: Record<string, unknown>) => api.post('/geo/aoi', data),
    delete: (id: number) => api.delete(`/geo/aoi/${id}`),
  },
  measure: (geojson: string | Record<string, unknown>) =>
    api.post('/geo/measure', { geojson }),
};

export const imageryApi = {
  search: (data: Record<string, unknown>) => api.post('/imagery/search', data),
  download: (
    scene_id: string,
    collection: string,
    extras?: {
      footprint_geojson?: string;
      product_id?: string;
      cloud_cover?: number;
      acquisition_date?: string;
      metadata?: Record<string, unknown>;
    },
  ) => api.post('/imagery/download', { scene_id, collection, ...extras }),
  cached: () => api.get('/imagery/cached'),
  footprints: () => api.get('/imagery/footprints'),
  copernicus: {
    authUrl: () => api.get('/imagery/copernicus/auth-url'),
    callback: (code: string) => api.post('/imagery/copernicus/callback', { code }),
    status: () => api.get('/imagery/copernicus/status'),
  },
};

export const analyticsApi = {
  computeIndex: (data: Record<string, unknown>) => api.post('/analytics/index', data),
  timeSeries: (data: Record<string, unknown>) => api.post('/analytics/time-series', data),
  histogram: (jobId: number) => api.get(`/analytics/histogram/${jobId}`),
  classify: (data: Record<string, unknown>) => api.post('/analytics/classify', data),
  changeDetection: (data: Record<string, unknown>) => api.post('/analytics/change-detection', data),
  detectWater: (data: Record<string, unknown>) => api.post('/analytics/detect/water', data),
  detectFlood: (data: Record<string, unknown>) => api.post('/analytics/detect/flood', data),
  detectBuilding: (data: Record<string, unknown>) => api.post('/analytics/detect/building', data),
  detectRoad: (data: Record<string, unknown>) => api.post('/analytics/detect/road', data),
  detectUrban: (data: Record<string, unknown>) => api.post('/analytics/detect/urban', data),
  jobs: () => api.get('/analytics/jobs'),
  report: (data: Record<string, unknown>) => api.post('/analytics/report', data),
  downloadReport: (filePath: string) =>
    api.get('/analytics/report/download', {
      params: { file_path: filePath },
      responseType: 'blob',
    }),
};

export const rasterApi = {
  upload: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api.post('/raster/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  info: (filePath: string) => api.get(`/raster/info/${encodeURIComponent(filePath)}`),
  convertCog: (filePath: string) =>
    api.post('/raster/convert-cog', null, { params: { file_path: filePath } }),
  importGeojson: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api.post('/raster/import/geojson', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  importShapefile: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api.post('/raster/import/shapefile', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  exportGeojson: (geojson: Record<string, unknown>, filename = 'export.geojson') =>
    api.post('/raster/export/geojson', geojson, {
      params: { filename },
      responseType: 'blob',
    }),
  exportShapefile: (geojson: Record<string, unknown>, filename = 'export.zip') =>
    api.post('/raster/export/shapefile', geojson, {
      params: { filename },
      responseType: 'blob',
    }),
};

export const adminApi = {
  stats: () => api.get('/admin/stats'),
  users: () => api.get('/admin/users'),
  projects: {
    list: () => api.get('/admin/projects'),
    create: (data: Record<string, unknown>) => api.post('/admin/projects', data),
  },
  subscription: () => api.get('/admin/subscription'),
  apiKeys: {
    list: () => api.get('/admin/api-keys'),
    create: (name: string) => api.post('/admin/api-keys', { name }),
    revoke: (id: number) => api.delete(`/admin/api-keys/${id}`),
  },
};

export const configApi = {
  health: () => axios.get('/api/health'),
  config: () => axios.get('/api/config'),
};

export const offlineApi = {
  status: () => api.get('/offline/status'),
  seed: () => api.post('/offline/seed'),
  layers: () => api.get('/offline/layers'),
  layerGeojson: (layerId: string) => api.get(`/offline/layers/${encodeURIComponent(layerId)}/geojson`),
  uploadElevation: (file: File, subtype = 'DEM') => {
    const form = new FormData();
    form.append('file', file);
    form.append('subtype', subtype);
    return api.post('/offline/layers/upload-elevation', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  uploadVector: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api.post('/offline/layers/upload-vector', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  tools: (params?: { category?: string; q?: string }) =>
    api.get('/offline/tools', { params }),
  toolCategories: () => api.get('/offline/tools/categories'),
  runTool: (tool_id: string, params: Record<string, unknown> = {}) =>
    api.post('/offline/tools/run', { tool_id, params }),
  stacks: () => api.get('/offline/stacks'),
  getStack: (id: string) => api.get(`/offline/stacks/${encodeURIComponent(id)}`),
  createStack: (data: Record<string, unknown>) => api.post('/offline/stacks', data),
  addImageToStack: (id: string, data: Record<string, unknown>) =>
    api.post(`/offline/stacks/${encodeURIComponent(id)}/images`, data),
  uploadToStack: (file: File, fields: {
    place_name: string;
    acquisition_date?: string;
    longitude?: number;
    latitude?: number;
    cloud_cover?: number;
  }) => {
    const form = new FormData();
    form.append('file', file);
    form.append('place_name', fields.place_name);
    if (fields.acquisition_date) form.append('acquisition_date', fields.acquisition_date);
    if (fields.longitude != null) form.append('longitude', String(fields.longitude));
    if (fields.latitude != null) form.append('latitude', String(fields.latitude));
    if (fields.cloud_cover != null) form.append('cloud_cover', String(fields.cloud_cover));
    return api.post('/offline/stacks/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  seedDemoStack: () => api.post('/offline/stacks/seed-demo'),
};
