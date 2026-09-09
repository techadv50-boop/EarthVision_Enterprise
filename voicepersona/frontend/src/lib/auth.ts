import type { Persona } from "./types";

export type AccountStatus = "pending" | "active" | "declined" | "restricted" | "expired";

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: "user" | "admin";
  status: string;
  subscription_ends_at: string | null;
  admin_note?: string;
  created_at: string;
  updated_at: string;
  subscription_active: boolean;
  days_remaining: number | null;
}

export interface PublicConfig {
  app_name: string;
  subscription_price: string;
  subscription_currency: string;
  subscription_days: number;
  reminder_days_before?: number;
}

const TOKEN_KEY = "voxpersona_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (!token) localStorage.removeItem(TOKEN_KEY);
  else localStorage.setItem(TOKEN_KEY, token);
}

export function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getToken();
  return {
    ...(extra || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

/** Keep Persona type import used for re-exports in app modules if needed */
export type { Persona };
