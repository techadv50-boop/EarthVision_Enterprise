import axios, { type AxiosInstance, type AxiosError } from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '/api/v1';

export const api: AxiosInstance = axios.create({
  baseURL: API_URL,
  // Eye-on prepares STAC match + preview COG read (Landsat can exceed 60s on cold start)
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('ev_access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    if (error.response?.status === 401) {
      const refresh = localStorage.getItem('ev_refresh_token');
      if (refresh && !error.config?.url?.includes('/auth/')) {
        try {
          const { data } = await axios.post(`${API_URL}/auth/refresh`, {
            refresh_token: refresh,
          });
          localStorage.setItem('ev_access_token', data.access_token);
          localStorage.setItem('ev_refresh_token', data.refresh_token);
          if (error.config) {
            error.config.headers.Authorization = `Bearer ${data.access_token}`;
            return api.request(error.config);
          }
        } catch {
          localStorage.removeItem('ev_access_token');
          localStorage.removeItem('ev_refresh_token');
          if (!window.location.pathname.includes('/login')) {
            window.location.href = '/login';
          }
        }
      }
    }
    return Promise.reject(error);
  },
);

export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((d) => d.msg || String(d)).join(', ');
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return 'Unexpected error';
}
