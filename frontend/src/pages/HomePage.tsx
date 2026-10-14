import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Puzzle, Shield, Upload } from 'lucide-react';
import { pluginApi } from '@/services/api';
import { BUILTIN_PLUGINS, type ToolPlugin } from '@/plugins/catalog';
import { pluginIcon } from '@/plugins/icons';
import { canManageUsers, hasService, isFullAdmin, useAuthStore, type ServiceId } from '@/store/authStore';

function canOpen(plugin: ToolPlugin, services: string[], admin: boolean): boolean {
  if (!plugin.enabled && !admin) return false;
  const service = plugin.service || 'open';
  if (service === 'open' || service === 'everyone') return true;
  if (service === 'admin' || service === 'operator') return admin;
  return services.includes(service);
}

export default function HomePage() {
  const user = useAuthStore((s) => s.user);
  const admin = canManageUsers(user);
  const operator = isFullAdmin(user);
  const services = (['citation', 'review', 'authors', 'galley'] as ServiceId[]).filter((id) =>
    hasService(user, id),
  );
  const [plugins, setPlugins] = useState<ToolPlugin[]>(BUILTIN_PLUGINS);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const { data } = await pluginApi.list();
        if (Array.isArray(data?.plugins)) setPlugins(data.plugins);
      } catch {
        setPlugins(BUILTIN_PLUGINS);
      } finally {
        setLoaded(true);
      }
    })();
  }, []);

  const tools = plugins.filter((plugin) => canOpen(plugin, services, operator));
  const anyTool = tools.some((plugin) => plugin.enabled);

  return (
    <div className="max-w-5xl mx-auto">
      <p className="text-xs uppercase tracking-[0.2em] text-earth-400 mb-2">XDGEN</p>
      <h2 className="text-3xl font-semibold mb-2">Tools</h2>
      <p className="text-gray-400 mb-8 max-w-3xl">
        Each card is a separate plugin. Open one tool, update one tool, or upload a new plugin
        without rebuilding the others.
        {admin ? ' Admins manage users. Operators can upload and replace plugins.' : ''}
      </p>
      {!anyTool && !admin && loaded && (
        <p className="panel p-6 text-gray-400 mb-6">
          No tools have been granted yet. Ask an admin to approve this account and tick the plugins
          this person may use.
        </p>
      )}
      <div className="grid gap-6 md:grid-cols-2">
        {tools.map((plugin) => {
          const Icon = pluginIcon(plugin.icon);
          const muted = !plugin.enabled;
          return (
            <Link
              key={plugin.id}
              to={plugin.enabled ? plugin.route : '/admin/plugins'}
              className={`panel p-8 hover:border-earth-500 transition-colors block min-h-[16rem] ${
                muted ? 'opacity-60' : ''
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <Icon className="w-10 h-10 text-earth-400 mb-4" />
                <span className="text-[11px] uppercase tracking-wide text-gray-500 border border-gray-800 rounded px-2 py-1">
                  {plugin.kind === 'uploaded' ? 'Uploaded plugin' : 'Built-in plugin'}
                </span>
              </div>
              <h3 className="text-2xl font-semibold">{plugin.name}</h3>
              <p className="text-gray-400 mt-3 leading-relaxed">{plugin.description}</p>
              <p className="text-xs text-gray-500 mt-4">
                {plugin.id} · v{plugin.version}
                {muted ? ' · disabled' : ''}
                {plugin.overridden ? ' · frontend replaced' : ''}
              </p>
              <p className="text-earth-400 text-sm mt-6">
                {muted ? 'Enable in plugin manager →' : `Open ${plugin.name} →`}
              </p>
            </Link>
          );
        })}
        {operator && (
          <Link
            to="/admin/plugins"
            className="panel p-8 hover:border-earth-500 transition-colors block min-h-[16rem] border-dashed"
          >
            <Upload className="w-10 h-10 text-earth-400 mb-4" />
            <h3 className="text-2xl font-semibold">Upload a plugin</h3>
            <p className="text-gray-400 mt-3 leading-relaxed">
              Operator only. Install a new tool as a zip (manifest.json + index.html), or replace
              one built-in tool by uploading a package with the same plugin id.
            </p>
            <p className="text-earth-400 text-sm mt-6">Open plugin manager →</p>
          </Link>
        )}
        {admin && (
          <Link
            to="/admin"
            className="panel p-8 hover:border-earth-500 transition-colors block min-h-[16rem]"
          >
            <Shield className="w-10 h-10 text-earth-400 mb-4" />
            <h3 className="text-2xl font-semibold">Admin</h3>
            <p className="text-gray-400 mt-3 leading-relaxed">
              Add users, approve or restrict accounts, and tick which plugins each person may use.
            </p>
            <p className="text-earth-400 text-sm mt-6">Manage users →</p>
          </Link>
        )}
        {!tools.length && !admin && !loaded && (
          <div className="panel p-8 text-gray-500 md:col-span-2 inline-flex items-center gap-2">
            <Puzzle className="w-5 h-5" /> Loading tools…
          </div>
        )}
      </div>
    </div>
  );
}
