import { authHeaders, getToken, setToken, type AuthUser, type PublicConfig } from "./auth";
import type {
  ChatMessage,
  ChatResponse,
  EngineInfo,
  MoodTag,
  Persona,
  PersonaTraits,
  SampleKind,
  SampleSource,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(authHeaders(init?.headers));
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const data = await res.json();
      message = data.error || JSON.stringify(data);
    } catch {
      message = await res.text();
    }
    const err = new Error(message || res.statusText) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  publicConfig: () => request<PublicConfig>("/api/public/config"),
  register: (body: { name: string; email: string; password: string }) =>
    request<{ ok: boolean; message: string; status: string }>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  login: async (body: { email: string; password: string }) => {
    const data = await request<{ token: string; user: AuthUser; warning?: string }>(
      "/api/auth/login",
      { method: "POST", body: JSON.stringify(body) },
    );
    setToken(data.token);
    return data;
  },
  logout: async () => {
    try {
      await request("/api/auth/logout", { method: "POST", body: "{}" });
    } finally {
      setToken(null);
    }
  },
  me: () =>
    request<{ user: AuthUser; config: PublicConfig }>("/api/auth/me"),
  renewRequest: () =>
    request<{ ok: boolean; message: string }>("/api/auth/renew-request", {
      method: "POST",
      body: "{}",
    }),
  adminUsers: () => request<AuthUser[]>("/api/admin/users"),
  adminAction: (userId: string, action: "allow" | "decline" | "restrict" | "renew", note = "") =>
    request<{ user: AuthUser }>(`/api/admin/users/${userId}/${action}`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  engines: () => request<{ engines: EngineInfo[] }>("/api/engines"),
  listPersonas: () => request<Persona[]>("/api/personas"),
  createPersona: (body: {
    name: string;
    description?: string;
    ai_engine?: string;
    traits?: Partial<PersonaTraits>;
  }) =>
    request<Persona>("/api/personas", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getPersona: (id: string) => request<Persona>(`/api/personas/${id}`),
  updatePersona: (
    id: string,
    body: Partial<{
      name: string;
      description: string;
      traits: PersonaTraits;
      ai_engine: string;
      voice_clone_id: string | null;
    }>,
  ) =>
    request<Persona>(`/api/personas/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deletePersona: (id: string) =>
    request<{ deleted: boolean }>(`/api/personas/${id}`, { method: "DELETE" }),
  uploadSample: async (
    personaId: string,
    file: Blob,
    meta: {
      kind: SampleKind;
      transcript: string;
      accent: string;
      talking_style: string;
      moods: MoodTag[];
      notes: string;
      duration_ms?: number;
      source?: SampleSource;
    },
    filename = "sample.webm",
  ) => {
    const form = new FormData();
    form.append("file", file, filename);
    form.append("meta", JSON.stringify(meta));
    return request(`/api/personas/${personaId}/samples`, {
      method: "POST",
      body: form,
    });
  },
  deleteSample: (personaId: string, sampleId: string) =>
    request<Persona>(`/api/personas/${personaId}/samples/${sampleId}`, {
      method: "DELETE",
    }),
  chat: (
    personaId: string,
    body: {
      message: string;
      history: ChatMessage[];
      mood?: MoodTag | null;
      speak?: boolean;
    },
  ) =>
    request<ChatResponse>(`/api/personas/${personaId}/chat`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

export function sampleAudioUrl(personaId: string, filename: string) {
  const token = getToken();
  const q = token ? `?token=${encodeURIComponent(token)}` : "";
  return `/api/personas/${personaId}/samples/${filename}/audio${q}`;
}
