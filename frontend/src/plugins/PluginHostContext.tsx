import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';

export type AoiBounds = {
  west: number;
  south: number;
  east: number;
  north: number;
} | null;

export type AnalysisResultEntry = {
  pluginId: string;
  version: string;
  title?: string;
  summary?: string;
  metrics?: Array<{ label: string; value: string | number }>;
  updatedAt: string;
};

type PluginHostContextValue = {
  aoiBounds: AoiBounds;
  setAoiBounds: (b: AoiBounds) => void;
  analysisByPlugin: Record<string, AnalysisResultEntry>;
  setAnalysisResult: (entry: AnalysisResultEntry) => void;
  getAnalysisResult: (pluginId: string) => AnalysisResultEntry | null;
};

const Ctx = createContext<PluginHostContextValue | null>(null);

export function PluginHostProvider({ children }: { children: ReactNode }) {
  const [aoiBounds, setAoiBounds] = useState<AoiBounds>(null);
  const [analysisByPlugin, setAnalysisByPlugin] = useState<
    Record<string, AnalysisResultEntry>
  >({});

  const value = useMemo<PluginHostContextValue>(
    () => ({
      aoiBounds,
      setAoiBounds,
      analysisByPlugin,
      setAnalysisResult: (entry) => {
        setAnalysisByPlugin((prev) => ({ ...prev, [entry.pluginId]: entry }));
      },
      getAnalysisResult: (pluginId) => analysisByPlugin[pluginId] || null,
    }),
    [aoiBounds, analysisByPlugin],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePluginHost(): PluginHostContextValue {
  const ctx = useContext(Ctx);
  if (!ctx) {
    // Fail soft when mounted outside provider (tests / partial trees)
    return {
      aoiBounds: null,
      setAoiBounds: () => undefined,
      analysisByPlugin: {},
      setAnalysisResult: () => undefined,
      getAnalysisResult: () => null,
    };
  }
  return ctx;
}
