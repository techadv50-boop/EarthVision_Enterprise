import type { Galley, IconAsset, Journal } from "./types";

const TOKEN_KEY = "galley-token";

export type Account = {
  id: string;
  name: string;
  email: string;
  role: "admin" | "user";
  status: "pending" | "approved" | "restricted";
};

export type GalleyRecord = {
  galley: Galley;
  ownerId: string;
  ownerName: string;
  ownerEmail: string;
};

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let detail = response.statusText || "Request failed";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* The server sent a non-JSON error. */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function register(name: string, email: string, password: string) {
  return request<{ ok: boolean; status: string }>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ name, email, password }),
  });
}

export function login(email: string, password: string) {
  return request<{ token: string; user: Account }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function me() {
  return request<Account>("/api/auth/me");
}

export function listUsers() {
  return request<Account[]>("/api/users");
}

export function addUser(name: string, email: string, password: string) {
  return request<Account>("/api/users", { method: "POST", body: JSON.stringify({ name, email, password }) });
}

export function setUserStatus(id: string, status: Account["status"]) {
  return request<Account>(`/api/users/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
}

export function journals() {
  return request<Journal[]>("/api/journals");
}

export function saveJournal(journal: Journal) {
  return request<Journal>("/api/journals", { method: "POST", body: JSON.stringify(journal) });
}

export function deleteJournal(id: string) {
  return request<{ ok: boolean }>(`/api/journals/${id}`, { method: "DELETE" });
}

export function galleys() {
  return request<GalleyRecord[]>("/api/galleys");
}

export function createGalley(galley: Galley) {
  return request<Galley>("/api/galleys", { method: "POST", body: JSON.stringify(galley) });
}

export function updateGalley(galley: Galley) {
  return request<Galley>(`/api/galleys/${galley.id}`, { method: "PUT", body: JSON.stringify(galley) });
}

export function deleteGalley(id: string) {
  return request<{ ok: boolean }>(`/api/galleys/${id}`, { method: "DELETE" });
}

export function openAccess() {
  return request<{ icon: IconAsset | null }>("/api/settings/open-access");
}

export function saveOpenAccess(icon: IconAsset | null) {
  return request<{ ok: boolean }>("/api/settings/open-access", { method: "PUT", body: JSON.stringify({ icon }) });
}

export function readEquation(dataUrl: string) {
  return request<{ text: string }>("/api/ocr", { method: "POST", body: JSON.stringify({ dataUrl }) });
}
