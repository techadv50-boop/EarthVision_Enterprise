import type {
  ChatMessage,
  ChatResponse,
  EngineInfo,
  MoodTag,
  Persona,
  PersonaTraits,
  SampleKind,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ ok: boolean }>("/api/health"),
  engines: () => request<{ engines: EngineInfo[] }>("/api/engines"),
  moods: () => request<{ moods: MoodTag[] }>("/api/moods"),
  listPersonas: () => request<Persona[]>("/api/personas"),
  createPersona: (body: {
    name: string;
    description?: string;
    ai_engine?: string;
    traits?: Partial<PersonaTraits>;
  }) =>
    request<Persona>("/api/personas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
      headers: { "Content-Type": "application/json" },
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
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

export function sampleAudioUrl(personaId: string, filename: string) {
  return `/api/personas/${personaId}/samples/${filename}/audio`;
}
