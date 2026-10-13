/**
 * Earth Vision Host SDK (E0/E1) — shell-side contracts for Tool Packs.
 *
 * E1 true_color does not load remote React. Packs expose ui/tool-meta.json;
 * the shell continues to own Leaflet overlays and calls the composite façade.
 * See docs/TOOL_PACK_FRONTEND_LOADING.md.
 */

import { api } from '../services/api';

export type ToolPin = {
  mode: 'builtin' | 'pack' | string;
  version?: string | null;
  digest?: string | null;
  updated_at?: string | null;
  note?: string;
};

export type ToolRuntimeInfo = {
  deployment_model: string;
  shell_deploy: string;
  pins: Record<string, ToolPin>;
  true_color: ToolPin;
};

export type TrueColorToolMeta = {
  tool_id: string;
  label: string;
  ui_strategy: string;
  facade: {
    action: { type: string; op: string };
    api: string;
    preset: string;
  };
  host_sdk: { react: string; leaflet: string };
};

export const hostSdk = {
  /** Runtime pins — which pack version the backend will use. */
  async getRuntime(): Promise<ToolRuntimeInfo> {
    const { data } = await api.get<ToolRuntimeInfo>('/tools/runtime');
    return data;
  },

  async getTrueColorMeta(version: string): Promise<TrueColorToolMeta> {
    const { data } = await api.get<TrueColorToolMeta>(
      `/tools/packs/true_color/${encodeURIComponent(version)}/meta`,
    );
    return data;
  },
};
