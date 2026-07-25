export type MoodTag =
  | "neutral"
  | "happy"
  | "sad"
  | "laughing"
  | "angry"
  | "excited"
  | "calm"
  | "anxious"
  | "affectionate"
  | "sarcastic";

export type SampleKind =
  | "speech"
  | "laughing"
  | "sadness"
  | "accent"
  | "style"
  | "other";

export type SampleSource = "family_talk" | "program_talk" | "upload" | string;

export interface VoiceSample {
  id: string;
  filename: string;
  kind: SampleKind;
  transcript: string;
  accent: string;
  talking_style: string;
  moods: MoodTag[];
  notes: string;
  duration_ms?: number | null;
  source?: SampleSource;
  created_at: string;
}

export interface PersonaTraits {
  language?: string;
  accent: string;
  talking_style: string;
  vocabulary_notes: string;
  laugh_style: string;
  sadness_style: string;
  filler_words: string[];
  catchphrases: string[];
  moods_observed: MoodTag[];
  extra: Record<string, unknown>;
}

export interface Persona {
  id: string;
  name: string;
  description: string;
  traits: PersonaTraits;
  samples: VoiceSample[];
  ai_engine: string;
  voice_clone_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  reply: string;
  engine: string;
  style_notes: string[];
  audio_url?: string | null;
}

export interface EngineInfo {
  id: string;
  name: string;
  description: string;
}

export type AppMode = "family" | "program" | "remember";
