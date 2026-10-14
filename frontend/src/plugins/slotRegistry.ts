/**
 * Host Shell plugin slot registry (Stage P1).
 *
 * Independent frontend bundles are NOT loaded into the shell.
 * Plugins declare a slot + host_component id in ui/tool-meta.json;
 * the shell maps that id to a first-party React component.
 *
 * Future isolation (Module Federation / import maps) is documented in
 * docs/PLUGIN_FRONTEND_BOUNDARY.md — prototype boundary only.
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

export type HostPluginComponentProps = {
  pluginId: string;
  version: string | null;
  name: string;
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
