import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { pluginApi } from '@/services/api';
import { pluginIcon } from '@/plugins/icons';
import type { ToolPlugin } from '@/plugins/catalog';

export default function PluginHostPage() {
  const { pluginId } = useParams();
  const [plugin, setPlugin] = useState<ToolPlugin | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    void (async () => {
      try {
        const { data } = await pluginApi.list();
        const found = (data.plugins as ToolPlugin[]).find((row) => row.id === pluginId);
        if (!found) {
          setError('That plugin is not installed, or this account cannot open it.');
          return;
        }
        setPlugin(found);
      } catch {
        setError('Could not load plugins.');
      }
    })();
  }, [pluginId]);

  const src = useMemo(() => {
    if (!plugin || plugin.kind !== 'uploaded') return '';
    const entry = (plugin.entry || 'index.html').replace(/^\/+/, '');
    return `/plugin-assets/${plugin.id}/${entry}`;
  }, [plugin]);

  if (error) {
    return (
      <div className="max-w-3xl mx-auto">
        <p className="text-red-400">{error}</p>
        <Link to="/" className="text-earth-400 text-sm mt-4 inline-block">
          Back to tools
        </Link>
      </div>
    );
  }
  if (!plugin) return <p className="text-gray-400">Loading plugin…</p>;
  if (!plugin.enabled) {
    return (
      <div className="max-w-3xl mx-auto">
        <p className="text-gray-400">{plugin.name} is disabled.</p>
        <Link to="/admin/plugins" className="text-earth-400 text-sm mt-4 inline-block">
          Plugin manager
        </Link>
      </div>
    );
  }
  if (plugin.kind !== 'uploaded' || !src) {
    return (
      <div className="max-w-3xl mx-auto">
        <p className="text-gray-400">This built-in tool opens on its own route.</p>
        <Link to={plugin.route} className="text-earth-400 text-sm mt-4 inline-block">
          Open {plugin.name}
        </Link>
      </div>
    );
  }

  const Icon = pluginIcon(plugin.icon);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3 px-1">
        <div className="flex items-center gap-2">
          <Icon className="w-5 h-5 text-earth-400" />
          <div>
            <h2 className="text-xl font-semibold">{plugin.name}</h2>
            <p className="text-xs text-gray-500">
              Uploaded plugin · {plugin.id} · v{plugin.version}
            </p>
          </div>
        </div>
        <Link to="/" className="text-sm text-gray-400 hover:text-white">
          All tools
        </Link>
      </div>
      <iframe
        title={plugin.name}
        src={src}
        className="w-full min-h-[80vh] rounded-lg border border-gray-800 bg-white"
      />
    </div>
  );
}
