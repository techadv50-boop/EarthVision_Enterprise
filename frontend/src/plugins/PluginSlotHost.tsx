import { useEffect, useState } from 'react';
import {
  pluginService,
  type PluginRecord,
  type PluginSlot,
} from '../services/pluginService';
import { SandboxedPluginFrame } from './SandboxedPluginFrame';
import { isSupportedSlot } from './slotRegistry';

interface Props {
  slot: PluginSlot;
  className?: string;
}

/**
 * Renders active plugins assigned to a Host Shell UI slot via sandboxed iframes.
 * Does not alter legacy toolbox / map workspace behavior when empty.
 */
export function PluginSlotHost({ slot, className }: Props) {
  const [plugins, setPlugins] = useState<PluginRecord[]>([]);

  useEffect(() => {
    if (!isSupportedSlot(slot)) {
      setPlugins([]);
      return;
    }
    let cancelled = false;
    pluginService
      .listActive(slot)
      .then((res) => {
        if (!cancelled) setPlugins(res.plugins || []);
      })
      .catch(() => {
        if (!cancelled) setPlugins([]);
      });
    return () => {
      cancelled = true;
    };
  }, [slot]);

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
