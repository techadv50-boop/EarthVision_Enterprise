/**
 * Host Shell plugin slot registry (Stage P2B).
 *
 * Independent plugin UI loads only via sandboxed iframe (srcdoc) + Host SDK.
 * Uploaded JavaScript never executes in the privileged React Host Shell.
 *
 * See docs/PLUGIN_FRONTEND_BOUNDARY.md.
 */

import type { ComponentType } from 'react';
import type { PluginSlot } from '../services/pluginService';
import { DemoHelloPanel } from './panels/DemoHelloPanel';

export const SUPPORTED_SLOTS: PluginSlot[] = [
  'left_toolbar',
  'right_analysis_panel',
  'map_overlay',
  'results_panel',
];

/** P1 static maps remain as a last-resort fallback when ui_strategy is shell_facade. */
export const P1_STATIC_HOST_MAPPINGS_ONLY = false as const;

export const P2B_SANDBOXED_IFRAME_LOADING = true as const;

export type HostPluginComponentProps = {
  pluginId: string;
  version: string | null;
  name: string;
  digest?: string | null;
};

const HOST_COMPONENTS: Record<string, ComponentType<HostPluginComponentProps>> = {
  DemoHelloPanel,
  demo_hello: DemoHelloPanel,
};

export function resolveHostPluginComponent(
  pluginId: string,
  hostComponent?: string | null,
): ComponentType<HostPluginComponentProps> | null {
  if (hostComponent && HOST_COMPONENTS[hostComponent]) {
    return HOST_COMPONENTS[hostComponent];
  }
  return HOST_COMPONENTS[pluginId] ?? null;
}

export function isSupportedSlot(slot: string): slot is PluginSlot {
  return (SUPPORTED_SLOTS as string[]).includes(slot);
}
