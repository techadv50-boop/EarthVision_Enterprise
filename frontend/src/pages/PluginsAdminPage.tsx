import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { pluginApi } from '@/services/api';
import { pluginIcon } from '@/plugins/icons';
import type { ToolPlugin } from '@/plugins/catalog';

export default function PluginsAdminPage() {
  const [plugins, setPlugins] = useState<ToolPlugin[]>([]);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');

  const load = async () => {
    const { data } = await pluginApi.list();
    setPlugins(data.plugins || []);
  };

  useEffect(() => {
    void load().catch(() => setError('Could not load plugins.'));
  }, []);

  const upload = async (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    setBusy('upload');
    setMsg('');
    setError('');
    try {
      const { data } = await pluginApi.upload(file);
      await load();
      setMsg(`Installed ${data.name} (${data.id} v${data.version}).`);
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      setError(typeof detail === 'string' ? detail : 'Could not install that zip.');
    } finally {
      setBusy('');
    }
  };

  const toggle = async (plugin: ToolPlugin, enabled: boolean) => {
    setBusy(plugin.id);
    setError('');
    try {
      await pluginApi.toggle(plugin.id, enabled);
      await load();
      setMsg(`${plugin.name} is ${enabled ? 'enabled' : 'disabled'}.`);
    } catch {
      setError('Could not change that plugin.');
    } finally {
      setBusy('');
    }
  };

  const remove = async (plugin: ToolPlugin) => {
    setBusy(plugin.id);
    setError('');
    try {
      await pluginApi.remove(plugin.id);
      await load();
      setMsg(
        plugin.kind === 'uploaded' && plugin.overridden
          ? `Restored the built-in ${plugin.name}.`
          : `Removed ${plugin.name}.`,
      );
    } catch {
      setError('Could not remove that plugin.');
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="max-w-4xl">
      <p className="text-sm text-gray-500 mb-2">
        <Link to="/admin">Admin</Link> / Plugins
      </p>
      <h2 className="text-2xl font-semibold mb-2">Plugin manager</h2>
      <p className="text-gray-400 text-sm mb-6 max-w-3xl">
        Built-in tools stay in the product. Upload a zip to add a new tool, or reuse a built-in id
        to replace only that tool’s frontend. Other plugins keep running.
      </p>
      {msg && <p className="text-earth-400 text-sm mb-3">{msg}</p>}
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      <div className="panel p-5 mb-6 space-y-3">
        <h3 className="font-medium">Upload plugin zip</h3>
        <p className="text-sm text-gray-400">
          Required files: <code className="text-gray-300">manifest.json</code> and the entry HTML
          (default <code className="text-gray-300">index.html</code>). Example manifest:
        </p>
        <pre className="text-xs bg-gray-950 border border-gray-800 rounded p-3 overflow-x-auto text-gray-300">{`{
  "id": "sample-tool",
  "name": "Sample tool",
  "description": "A new desk",
  "version": "1.0.0",
  "service": "open",
  "icon": "puzzle",
  "entry": "index.html"
}`}</pre>
        <p className="text-xs text-gray-500">
          <code className="text-gray-400">service</code> may be citation, review, authors, galley,
          open (everyone signed in), or admin. Replacing a built-in tool: use that tool’s id, for
          example <code className="text-gray-400">galley-composition</code>.
        </p>
        <label className="btn-primary cursor-pointer inline-block">
          {busy === 'upload' ? 'Installing…' : 'Choose zip'}
          <input
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            disabled={busy === 'upload'}
            onChange={(e) => void upload(e.target.files)}
          />
        </label>
      </div>

      <div className="space-y-3">
        {plugins.map((plugin) => {
          const Icon = pluginIcon(plugin.icon);
          return (
            <div key={plugin.id} className="panel p-4 flex flex-wrap gap-4 justify-between">
              <div className="flex gap-3 min-w-[16rem] flex-1">
                <Icon className="w-8 h-8 text-earth-400 shrink-0" />
                <div>
                  <p className="font-medium">{plugin.name}</p>
                  <p className="text-xs text-gray-500 mt-1">
                    {plugin.id} · v{plugin.version} · {plugin.kind}
                    {plugin.overridden ? ' override' : ''} · {plugin.service} privilege
                    {plugin.enabled ? '' : ' · disabled'}
                  </p>
                  <p className="text-sm text-gray-400 mt-2">{plugin.description}</p>
                </div>
              </div>
              <div className="flex flex-wrap gap-2 items-start">
                <button
                  className="btn-secondary"
                  type="button"
                  disabled={busy === plugin.id}
                  onClick={() => void toggle(plugin, !plugin.enabled)}
                >
                  {plugin.enabled ? 'Disable' : 'Enable'}
                </button>
                {(plugin.kind === 'uploaded' || plugin.overridden) && (
                  <button
                    className="btn-secondary"
                    type="button"
                    disabled={busy === plugin.id}
                    onClick={() => void remove(plugin)}
                  >
                    {plugin.overridden ? 'Restore built-in' : 'Remove'}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
