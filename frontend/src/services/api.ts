import axios, { type AxiosInstance, type AxiosError } from 'axios';

export const API_URL = import.meta.env.VITE_API_URL || '/api/v1';

/** Thrown by fetch-based helpers so UI can reuse getErrorMessage. */
export class ApiHttpError extends Error {
  status: number;
  detail: unknown;
  data: unknown;

  constructor(status: number, data: unknown) {
    const detail =
      data && typeof data === 'object' && 'detail' in data
        ? (data as { detail: unknown }).detail
        : undefined;
    super(formatDetail(detail) || `Request failed with status code ${status}`);
    this.name = 'ApiHttpError';
    this.status = status;
    this.detail = detail;
    this.data = data;
  }
}

function formatDetail(detail: unknown): string {
  if (typeof detail === 'string' && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (d && typeof d === 'object' && 'msg' in d) {
          const loc = Array.isArray((d as { loc?: unknown }).loc)
            ? (d as { loc: unknown[] }).loc.join('.')
            : '';
          const msg = String((d as { msg: unknown }).msg || d);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return String(d);
      })
      .filter(Boolean)
      .join('; ');
  }
  if (detail && typeof detail === 'object') return JSON.stringify(detail);
  return '';
}

// Slightly above server 55s render budget so users see our 504 message,
// not the opaque "timeout of 60000ms exceeded" axios error.
export const api: AxiosInstance = axios.create({
  baseURL: API_URL,
  timeout: 75000,
  // Do NOT default Content-Type to application/json — that breaks FormData
  // uploads (plugin zip validate-upload) because multipart boundary is lost.
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('ev_access_token');
  if (token) {
    if (typeof config.headers?.set === 'function') {
      config.headers.set('Authorization', `Bearer ${token}`);
    } else {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }

  const isForm =
    typeof FormData !== 'undefined' && config.data instanceof FormData;
  if (isForm) {
    // Axios 1.x: false deletes Content-Type so the browser sets multipart + boundary.
    const headers = config.headers as {
      setContentType?: (v: false) => void;
      delete?: (k: string) => void;
    };
    if (typeof headers.setContentType === 'function') {
      headers.setContentType(false);
    } else {
      headers.delete?.('Content-Type');
      headers.delete?.('content-type');
    }
  } else if (config.data != null && typeof config.data === 'object') {
    if (typeof config.headers?.set === 'function') {
      config.headers.set('Content-Type', 'application/json');
    } else {
      (config.headers as Record<string, string>)['Content-Type'] = 'application/json';
    }
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

/**
 * Upload a file as multipart/form-data via fetch (not axios).
 * Axios + default JSON Content-Type previously caused FastAPI 422
 * ``body.file Field required`` on /admin/plugins/validate-upload.
 */
export async function postMultipartFile<T = Record<string, unknown>>(
  path: string,
  file: File,
  fieldName = 'file',
): Promise<T> {
  const body = new FormData();
  body.append(fieldName, file, file.name);

  const headers: Record<string, string> = {};
  const token = localStorage.getItem('ev_access_token');
  if (token) headers.Authorization = `Bearer ${token}`;
  // Intentionally omit Content-Type — browser sets multipart boundary.

  const url = path.startsWith('http')
    ? path
    : `${API_URL.replace(/\/$/, '')}/${path.replace(/^\//, '')}`;

  const res = await fetch(url, {
    method: 'POST',
    headers,
    body,
    credentials: 'same-origin',
  });

  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }

  if (!res.ok) {
    throw new ApiHttpError(res.status, data);
  }
  return data as T;
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof ApiHttpError) {
    return error.message || `Request failed with status code ${error.status}`;
  }
  if (axios.isAxiosError(error)) {
    const status = error.response?.status;
    const detail = error.response?.data?.detail;
    const fromDetail = formatDetail(detail);
    if (fromDetail) return fromDetail;

    const code = error.code;
    if (
      code === 'ECONNABORTED' ||
      /timeout/i.test(error.message) ||
      status === 504
    ) {
      return 'Request timed out — zoom in or retry. Previews stay small on slow links.';
    }
    if (status === 502 || status === 503 || status === 520 || status === 524) {
      return 'Server temporarily unavailable — please retry in a moment.';
    }
    if (status === 500) {
      return 'Internal server error — please retry. If it persists, turn the eye off/on.';
    }
    if (status === 422) {
      return 'Validation failed (422) — check Network → Response for detail.';
    }
    return error.message || 'Request failed';
  }
  if (error instanceof Error) return error.message;
  return 'Unexpected error';
}
