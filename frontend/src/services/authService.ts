import { api } from './api';

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: 'admin' | 'analyst' | 'viewer' | 'billing';
  is_active: boolean;
  is_verified: boolean;
  organization?: string | null;
  avatar_url?: string | null;
  /** null = all toolboxes; list = only those toolbox ids */
  allowed_tools?: string[] | null;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export const authService = {
  async login(email: string, password: string): Promise<TokenResponse> {
    const { data } = await api.post<TokenResponse>('/auth/login', { email, password });
    localStorage.setItem('ev_access_token', data.access_token);
    localStorage.setItem('ev_refresh_token', data.refresh_token);
    return data;
  },

  async register(payload: {
    email: string;
    password: string;
    full_name: string;
    organization?: string;
  }): Promise<User> {
    const { data } = await api.post<User>('/auth/register', payload);
    return data;
  },

  async me(): Promise<User> {
    const { data } = await api.get<User>('/auth/me');
    return data;
  },

  logout(): void {
    localStorage.removeItem('ev_access_token');
    localStorage.removeItem('ev_refresh_token');
  },

  isAuthenticated(): boolean {
    return Boolean(localStorage.getItem('ev_access_token'));
  },
};
