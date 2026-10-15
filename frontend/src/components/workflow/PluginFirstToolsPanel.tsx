import { useCallback, useEffect, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  FolderPlus,
  FolderTree,
  Package,
  Upload,
  Wrench,
  X,
} from 'lucide-react';
import {
  toolTreeService,
  type ToolCategoryNode,
  type ToolPlacementNode,
} from '../../services/toolTreeService';

interface Props {
  isAdmin: boolean;
  onClose: () => void;
  onOpenAdminTools: (tab: 'plugins' | 'tool-tree' | 'upload') => void;
  onOpenTool: (placement: ToolPlacementNode) => void;
  selectedPluginId?: string | null;
}

function CategoryBranch({
  node,
  depth,
  selectedPluginId,
  onOpenTool,
}: {
  node: ToolCategoryNode;
  depth: number;
  selectedPluginId?: string | null;
  onOpenTool: (p: ToolPlacementNode) => void;
}) {
  const [open, setOpen] = useState(!node.collapsed_default);
  return (
    <div className="select-none" style={{ paddingLeft: depth ? 8 : 0 }}>
      <button
        type="button"
        className="flex w-full items-center gap-1 rounded px-1.5 py-1 text-left text-xs font-semibold text-[var(--ink)] hover:bg-[var(--bg)]"
        onClick={() => setOpen((v) => !v)}
        data-testid={`tool-cat-${node.id}`}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <span className="truncate">{node.name}</span>
      </button>
      {open && (
        <div className="ml-2 border-l border-[var(--line)] pl-1">
          {node.placements.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`mb-0.5 flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-left text-xs ${
                selectedPluginId === p.plugin_id
                  ? 'bg-[var(--accent-soft)] font-semibold text-[var(--accent)]'
                  : 'text-[var(--ink)] hover:bg-[var(--bg)]'
              }`}
              onClick={() => onOpenTool(p)}
              data-testid={`tool-item-${p.plugin_id}`}
              title={p.description || p.display_name}
            >
              <Wrench className="h-3 w-3 shrink-0 opacity-70" />
              <span className="truncate">{p.display_name}</span>
            </button>
          ))}
          {node.children.map((ch) => (
            <CategoryBranch
              key={ch.id}
              node={ch}
              depth={depth + 1}
              selectedPluginId={selectedPluginId}
              onOpenTool={onOpenTool}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Plugin-first analytical tools panel. Host Platform map/layers remain elsewhere.
 * Clean install shows empty state — no hardcoded 148-tool catalog.
 */
export function PluginFirstToolsPanel({
  isAdmin,
  onClose,
  onOpenAdminTools,
  onOpenTool,
  selectedPluginId,
}: Props) {
  const [tree, setTree] = useState<ToolTreeResponseLike | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  type ToolTreeResponseLike = Awaited<ReturnType<typeof toolTreeService.getTree>>;

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await toolTreeService.getTree();
      setTree(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load tool tree');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const empty = !loading && (tree?.empty || !(tree?.roots?.length));

  return (
    <aside
      className="flex h-full flex-col border-l border-[var(--line)] bg-white"
      data-testid="plugin-first-tools-panel"
    >
      <div className="flex items-center justify-between border-b border-[var(--line)] px-3 py-2">
        <div className="flex items-center gap-1.5 text-sm font-semibold">
          <FolderTree className="h-4 w-4 text-[var(--accent)]" />
          Tools
        </div>
        <button type="button" className="ev-btn-ghost p-1.5" onClick={onClose} title="Close">
          <X className="h-4 w-4" />
        </button>
      </div>

      {isAdmin && (
        <div className="flex flex-wrap gap-1.5 border-b border-[var(--line)] px-3 py-2">
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md bg-[var(--accent)] px-2 py-1 text-[11px] font-semibold text-white"
            onClick={() => onOpenAdminTools('upload')}
            data-testid="btn-upload-tool"
          >
            <Upload className="h-3 w-3" />
            Upload Tool Plugin
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md border border-[var(--line)] px-2 py-1 text-[11px] font-semibold"
            onClick={() => onOpenAdminTools('tool-tree')}
            data-testid="btn-create-category"
          >
            <FolderPlus className="h-3 w-3" />
            Create Category
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md border border-[var(--line)] px-2 py-1 text-[11px] font-semibold"
            onClick={() => onOpenAdminTools('tool-tree')}
          >
            <FolderTree className="h-3 w-3" />
            Manage Tool Tree
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md border border-[var(--line)] px-2 py-1 text-[11px] font-semibold"
            onClick={() => onOpenAdminTools('plugins')}
          >
            <Package className="h-3 w-3" />
            Manage Installed Plugins
          </button>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {loading && <p className="text-xs text-[var(--muted)]">Loading tools…</p>}
        {error && (
          <p className="rounded border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-700">
            {error}
          </p>
        )}
        {empty && !error && (
          <div
            className="rounded-lg border border-dashed border-[var(--line)] bg-[var(--bg)] px-3 py-6 text-center"
            data-testid="tools-empty-state"
          >
            <p className="text-sm font-medium text-[var(--ink)]">
              No tools installed. Create a category or upload your first tool.
            </p>
            <p className="mt-2 text-xs text-[var(--muted)]">
              Analytical tools are plugins. The Host Platform map, layers, and imagery stay
              available without a core rebuild.
            </p>
            {isAdmin && (
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                <button
                  type="button"
                  className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-white"
                  onClick={() => onOpenAdminTools('upload')}
                >
                  + Upload Tool Plugin
                </button>
                <button
                  type="button"
                  className="rounded-md border border-[var(--line)] px-3 py-1.5 text-xs font-semibold"
                  onClick={() => onOpenAdminTools('tool-tree')}
                >
                  + Create Category
                </button>
              </div>
            )}
          </div>
        )}
        {!empty &&
          tree?.roots?.map((root) => (
            <CategoryBranch
              key={root.id}
              node={root}
              depth={0}
              selectedPluginId={selectedPluginId}
              onOpenTool={onOpenTool}
            />
          ))}
      </div>
    </aside>
  );
}
