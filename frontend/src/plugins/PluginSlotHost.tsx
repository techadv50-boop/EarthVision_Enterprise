import { useEffect, useState } from 'react';
import {
  pluginService,
  type PluginRecord,
  type PluginSlot,
} from '../services/pluginService';
import { toolTreeService } from '../services/toolTreeService';
import { SandboxedPluginFrame } from './SandboxedPluginFrame';
import { isSupportedSlot } from './slotRegistry';

interface Props {
  slot: PluginSlot;
  className?: string;
  /** When set, only render this plugin in the slot (user opened from tool tree). */
  focusPluginId?: string | null;
}

/**
 * Renders active plugins for a Host Shell UI slot via sandboxed iframes.
 * Prefers tool-tree execution placement; falls back to plugin registry slot.
 */
export function PluginSlotHost({ slot, className, focusPluginId }: Props) {
  const [plugins, setPlugins] = useState<PluginRecord[]>([]);

  useEffect(() => {
    if (!isSupportedSlot(slot)) {
      setPlugins([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const placed = await toolTreeService.activeForSlot(slot);
        let list = (placed.plugins || []).map(
          (p) =>
            ({
              plugin_id: p.plugin_id,
              name: p.display_name || p.name || p.plugin_id,
              description: p.description || '',
              version: p.plugin_version || p.version || null,
              compatible_host_api: '>=1.0.0,<2',
              backend_entrypoint: 'backend/plugin.py',
              frontend_slot: slot,
              permissions: p.permissions || [],
              installation_status: 'installed',
              activation_status: 'active',
              digest: p.plugin_digest || p.digest || null,
            }) as PluginRecord,
        );
        if (!list.length) {
          const legacy = await pluginService.listActive(slot);
          list = legacy.plugins || [];
        }
        if (focusPluginId) {
          list = list.filter((p) => p.plugin_id === focusPluginId);
        }
        if (!cancelled) setPlugins(list);
      } catch {
        if (!cancelled) setPlugins([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [slot, focusPluginId]);

  if (!plugins.length) return null;

  return (
    <div className={className} data-plugin-slot={slot}>
      {plugins.map((p) => (
        <SandboxedPluginFrame
          key={`${p.plugin_id}:${p.version}:${p.digest || ''}`}
          pluginId={p.plugin_id}
          version={p.version || '0.0.0'}
          name={p.name || p.plugin_id}
          digest={p.digest}
          slot={slot}
        />
      ))}
    </div>
  );
}
