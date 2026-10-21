import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { TrueColorBandRecipe } from './trueColorBands';

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

/** Active scene snapshot for sandboxed optical plugins (no Leaflet). */
export type PluginSceneContext = {
  scene_id: string | null;
  collection: string | null;
  family: string | null;
  label: string | null;
  optical_ok: boolean;
  optical_block_reason: string | null;
  bounds: [number, number, number, number] | null;
  band_recipe: TrueColorBandRecipe | null;
  has_true_color_overlay: boolean;
};

export type ExportMapJpegParams = {
  dpi?: 300 | 600;
  title?: string;
};

export type PluginImageryHandlers = {
  renderTrueColor: () => Promise<Record<string, unknown>>;
  exportGeotiff: () => Promise<Record<string, unknown>>;
  exportMapJpeg: (params: ExportMapJpegParams) => Promise<Record<string, unknown>>;
};

type PluginHostContextValue = {
  aoiBounds: AoiBounds;
  setAoiBounds: (b: AoiBounds) => void;
  analysisByPlugin: Record<string, AnalysisResultEntry>;
  setAnalysisResult: (entry: AnalysisResultEntry) => void;
  getAnalysisResult: (pluginId: string) => AnalysisResultEntry | null;
  sceneContext: PluginSceneContext | null;
  setSceneContext: (ctx: PluginSceneContext | null) => void;
  setImageryHandlers: (handlers: PluginImageryHandlers | null) => void;
  getImageryHandlers: () => PluginImageryHandlers | null;
};

const Ctx = createContext<PluginHostContextValue | null>(null);

const EMPTY_SCENE: PluginSceneContext = {
  scene_id: null,
  collection: null,
  family: null,
  label: null,
  optical_ok: false,
  optical_block_reason: 'Select an optical satellite scene first.',
  bounds: null,
  band_recipe: null,
  has_true_color_overlay: false,
};

export function PluginHostProvider({ children }: { children: ReactNode }) {
  const [aoiBounds, setAoiBounds] = useState<AoiBounds>(null);
  const [analysisByPlugin, setAnalysisByPlugin] = useState<
    Record<string, AnalysisResultEntry>
  >({});
  const [sceneContext, setSceneContext] = useState<PluginSceneContext | null>(null);
  const imageryHandlersRef = useRef<PluginImageryHandlers | null>(null);

  const setImageryHandlers = useCallback((handlers: PluginImageryHandlers | null) => {
    imageryHandlersRef.current = handlers;
  }, []);

  const getImageryHandlers = useCallback(() => imageryHandlersRef.current, []);

  const value = useMemo<PluginHostContextValue>(
    () => ({
      aoiBounds,
      setAoiBounds,
      analysisByPlugin,
      setAnalysisResult: (entry) => {
        setAnalysisByPlugin((prev) => ({ ...prev, [entry.pluginId]: entry }));
      },
      getAnalysisResult: (pluginId) => analysisByPlugin[pluginId] || null,
      sceneContext,
      setSceneContext,
      setImageryHandlers,
      getImageryHandlers,
    }),
    [aoiBounds, analysisByPlugin, sceneContext, setImageryHandlers, getImageryHandlers],
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
      sceneContext: EMPTY_SCENE,
      setSceneContext: () => undefined,
      setImageryHandlers: () => undefined,
      getImageryHandlers: () => null,
    };
  }
  return ctx;
}
