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
  /** Optional: remove host-applied true-color overlay when tool is unchecked. */
  clearTrueColor?: () => Promise<void> | void;
};

/** Workspace tool-row status (selected / processing / applied / failed). */
export type ToolRunStatus = 'idle' | 'selected' | 'processing' | 'applied' | 'failed';

export type ToolRunEntry = {
  pluginId: string;
  displayName?: string;
  status: ToolRunStatus;
  message?: string;
  updatedAt: string;
};

type PluginHostContextValue = {
  aoiBounds: AoiBounds;
  setAoiBounds: (b: AoiBounds) => void;
  analysisByPlugin: Record<string, AnalysisResultEntry>;
  setAnalysisResult: (entry: AnalysisResultEntry) => void;
  clearAnalysisResult: (pluginId: string) => void;
  getAnalysisResult: (pluginId: string) => AnalysisResultEntry | null;
  toolRunByPlugin: Record<string, ToolRunEntry>;
  setToolRunStatus: (entry: ToolRunEntry) => void;
  clearToolRun: (pluginId: string) => void;
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
  const [toolRunByPlugin, setToolRunByPlugin] = useState<Record<string, ToolRunEntry>>({});
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
        setToolRunByPlugin((prev) => ({
          ...prev,
          [entry.pluginId]: {
            pluginId: entry.pluginId,
            displayName: entry.title || prev[entry.pluginId]?.displayName,
            status: 'applied',
            message: entry.summary || 'Result ready',
            updatedAt: entry.updatedAt,
          },
        }));
      },
      clearAnalysisResult: (pluginId) => {
        setAnalysisByPlugin((prev) => {
          const next = { ...prev };
          delete next[pluginId];
          return next;
        });
      },
      getAnalysisResult: (pluginId) => analysisByPlugin[pluginId] || null,
      toolRunByPlugin,
      setToolRunStatus: (entry) => {
        setToolRunByPlugin((prev) => ({ ...prev, [entry.pluginId]: entry }));
      },
      clearToolRun: (pluginId) => {
        setToolRunByPlugin((prev) => {
          const next = { ...prev };
          delete next[pluginId];
          return next;
        });
      },
      sceneContext,
      setSceneContext,
      setImageryHandlers,
      getImageryHandlers,
    }),
    [
      aoiBounds,
      analysisByPlugin,
      toolRunByPlugin,
      sceneContext,
      setImageryHandlers,
      getImageryHandlers,
    ],
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
      clearAnalysisResult: () => undefined,
      getAnalysisResult: () => null,
      toolRunByPlugin: {},
      setToolRunStatus: () => undefined,
      clearToolRun: () => undefined,
      sceneContext: EMPTY_SCENE,
      setSceneContext: () => undefined,
      setImageryHandlers: () => undefined,
      getImageryHandlers: () => null,
    };
  }
  return ctx;
}
