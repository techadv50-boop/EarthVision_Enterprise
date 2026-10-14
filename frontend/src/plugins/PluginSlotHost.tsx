import { useEffect, useState } from 'react';
import {
  pluginService,
  type PluginRecord,
  type PluginSlot,
} from '../services/pluginService';
import { resolveHostPluginComponent } from './slotRegistry';

interface Props {
  slot: PluginSlot;
  className?: string;
}

/**
 * Renders active plugins assigned to a Host Shell UI slot.
 * Does not alter legacy toolbox / map workspace behavior when empty.
 */
export function PluginSlotHost({ slot, className }: Props) {
  const [plugins, setPlugins] = useState<PluginRecord[]>([]);

  useEffect(() => {
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
      {plugins.map((p) => {
        const Comp = resolveHostPluginComponent(p.plugin_id);
        if (!Comp) {
          return (
            <div key={p.plugin_id} className="p-2 text-xs text-[var(--muted)]">
              Plugin {p.plugin_id} has no host component mapping (remote bundles blocked in P1).
            </div>
          );
        }
        return (
          <Comp
            key={p.plugin_id}
            pluginId={p.plugin_id}
            version={p.version}
            name={p.name || p.plugin_id}
          />
        );
      })}
    </div>
  );
}
