import { pluginByRoute } from '@/plugins/catalog';

export default function ToolBanner({ path }: { path: string }) {
  const plugin = pluginByRoute(path);
  if (!plugin) return null;
  return (
    <p className="text-xs text-gray-500 mb-4">
      Plugin <span className="text-earth-400">{plugin.id}</span>
      <span className="text-gray-600"> · </span>
      v{plugin.version}
      <span className="text-gray-600"> · </span>
      update this tool without touching the others
    </p>
  );
}
