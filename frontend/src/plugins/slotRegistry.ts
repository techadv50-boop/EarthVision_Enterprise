/**
 * Host Shell plugin slot registry (Stage P1 / P1.1).
 *
 * P1 LIMITATION: only static first-party Host Shell component mappings are
 * supported. Independent frontend plugin bundles are NOT loaded.
 *
 * Do NOT enable arbitrary remote JavaScript or unrestricted Module Federation.
 * The secure loading contract is defined in docs/PLUGIN_FRONTEND_BOUNDARY.md
 * and is not activated in this stage.
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

/** @deprecated P1 limitation — static host maps only; not a plugin loader. */
export const P1_STATIC_HOST_MAPPINGS_ONLY = true as const;

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
