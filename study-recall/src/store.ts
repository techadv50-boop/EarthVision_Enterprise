import { create } from "zustand";
import { api, errorText } from "./api";
import type { ModelInfo, Profile, Settings } from "./types";

type SessionState = {
  ready: boolean;
  error: string;
  settings: Settings | null;
  profiles: Profile[];
  models: ModelInfo[];
  dataDirectory: string;
  recoveryPolicy: string;
  refresh: () => Promise<void>;
  applySettings: (settings: Settings) => void;
  applyModels: (models: ModelInfo[]) => void;
  setTheme: (theme: "light" | "dark") => Promise<void>;
};

function applyTheme(theme: string) {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

export const useSession = create<SessionState>((set) => ({
  ready: false,
  error: "",
  settings: null,
  profiles: [],
  models: [],
  dataDirectory: "",
  recoveryPolicy: "",
  refresh: async () => {
    try {
      const data = await api.bootstrap();
      applyTheme(data.settings.theme);
      set({
        ready: true,
        error: "",
        settings: data.settings,
        profiles: data.profiles,
        models: data.models,
        dataDirectory: data.dataDirectory,
        recoveryPolicy: data.recoveryPolicy,
      });
    } catch (err) {
      set({ ready: true, error: errorText(err) });
    }
  },
  applySettings: (settings) => {
    applyTheme(settings.theme);
    set({ settings });
  },
  applyModels: (models) => set({ models }),
  setTheme: async (theme) => {
    const settings = await api.updateSettings({ theme });
    applyTheme(settings.theme);
    set({ settings });
  },
}));

export function useStudent(): Profile | null {
  const settings = useSession((state) => state.settings);
  const profiles = useSession((state) => state.profiles);
  if (!settings?.activeStudentId) return null;
  return profiles.find((profile) => profile.id === settings.activeStudentId) ?? null;
}
