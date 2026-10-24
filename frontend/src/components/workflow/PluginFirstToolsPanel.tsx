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
import type { ToolRunEntry, ToolRunStatus } from '../../plugins/PluginHostContext';

interface Props {
  isAdmin: boolean;
  onClose: () => void;
  onOpenAdminTools: (tab: 'plugins' | 'tool-tree' | 'upload') => void;
  /** Toggle check/uncheck — re-clicking a checked tool unselects it. */
  onToggleTool: (placement: ToolPlacementNode, checked: boolean) => void;
  selectedPluginId?: string | null;
  toolRuns?: Record<string, ToolRunEntry>;
}

function statusLabel(status: ToolRunStatus | undefined): { text: string; cls: string } {
  switch (status) {
    case 'processing':
      return { text: 'Processing…', cls: 'bg-amber-100 text-amber-900' };
    case 'applied':
      return { text: 'Applied', cls: 'bg-emerald-100 text-emerald-800' };
    case 'failed':
      return { text: 'Failed', cls: 'bg-red-100 text-red-800' };
    case 'selected':
      return { text: 'Selected', cls: 'bg-sky-100 text-sky-900' };
    default:
      return { text: '', cls: '' };
  }
}

function CategoryBranch({
  node,
  depth,
  selectedPluginId,
  onToggleTool,
  toolRuns,
}: {
  node: ToolCategoryNode;
  depth: number;
  selectedPluginId?: string | null;
  onToggleTool: (p: ToolPlacementNode, checked: boolean) => void;
  toolRuns?: Record<string, ToolRunEntry>;
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
          {node.placements.map((p) => {
            const checked = selectedPluginId === p.plugin_id;
            const run = toolRuns?.[p.plugin_id];
            const badge = statusLabel(run?.status);
            return (
              <label
                key={p.id}
                className={`mb-0.5 flex w-full cursor-pointer items-start gap-1.5 rounded px-2 py-1.5 text-left text-xs ${
                  checked
                    ? 'bg-[var(--accent-soft)] font-semibold text-[var(--accent)]'
                    : 'text-[var(--ink)] hover:bg-[var(--bg)]'
                }`}
                data-testid={`tool-item-${p.plugin_id}`}
                title={
                  run?.message ||
                  p.description ||
                  p.display_name ||
                  'Check to apply · uncheck to clear'
                }
              >
                <input
                  type="checkbox"
                  className="mt-0.5 shrink-0"
                  checked={checked}
                  onChange={(e) => onToggleTool(p, e.target.checked)}
                  data-testid={`tool-check-${p.plugin_id}`}
                />
                <Wrench className="mt-0.5 h-3 w-3 shrink-0 opacity-70" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{p.display_name}</span>
                  {badge.text && (
                    <span
                      className={`mt-0.5 inline-block rounded px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${badge.cls}`}
                      data-testid={`tool-status-${p.plugin_id}`}
                    >
                      {badge.text}
                    </span>
                  )}
                  {run?.message && (run.status === 'failed' || run.status === 'processing') && (
                    <span className="mt-0.5 block text-[10px] font-normal text-[var(--muted)]">
                      {run.message}
                    </span>
                  )}
                </span>
              </label>
            );
          })}
          {node.children.map((ch) => (
            <CategoryBranch
              key={ch.id}
              node={ch}
              depth={depth + 1}
              selectedPluginId={selectedPluginId}
              onToggleTool={onToggleTool}
              toolRuns={toolRuns}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Plugin-first analytical tools panel.
 * Check a tool to apply / open it; uncheck to clear selection and host apply state.
 */
export function PluginFirstToolsPanel({
  isAdmin,
  onClose,
  onOpenAdminTools,
  onToggleTool,
  selectedPluginId,
  toolRuns,
}: Props) {
  const [tree, setTree] = useState<ToolTreeResponseLike | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [newCategoryName, setNewCategoryName] = useState('');
  const [creating, setCreating] = useState(false);

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
  const activeRun = selectedPluginId ? toolRuns?.[selectedPluginId] : null;

  async function createRootCategory() {
    const name = newCategoryName.trim();
    if (!name || creating) return;
    setCreating(true);
    setError(null);
    try {
      const res = await toolTreeService.createCategory({ name });
      if (res.ok === false) {
        setError(String(res.error || 'Could not create category'));
        return;
      }
      setNewCategoryName('');
      await refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not create category');
    } finally {
      setCreating(false);
    }
  }

  return (
    <aside
      className="flex h-full flex-col border-l border-[var(--line)] bg-white"
      data-testid="plugin-first-tools-panel"
    >
      <div className="flex items-center justify-between border-b border-[var(--line)] px-3 py-2">
        <div>
          <div className="flex items-center gap-1.5 text-sm font-semibold">
            <FolderTree className="h-4 w-4 text-[var(--accent)]" />
            Tools
          </div>
          <p className="mt-0.5 text-[10px] text-[var(--muted)]">
            Check a tool to apply · uncheck to clear · status shows on each row
          </p>
        </div>
        <button type="button" className="ev-btn-ghost p-1.5" onClick={onClose} title="Close">
          <X className="h-4 w-4" />
        </button>
      </div>

      {activeRun && (
        <div
          className="border-b border-[var(--line)] px-3 py-2 text-[11px]"
          data-testid="tool-run-banner"
        >
          <span className="font-semibold">{activeRun.displayName || activeRun.pluginId}</span>
          {': '}
          <span
            className={
              activeRun.status === 'failed'
                ? 'text-red-700'
                : activeRun.status === 'applied'
                  ? 'text-emerald-800'
                  : activeRun.status === 'processing'
                    ? 'text-amber-900'
                    : 'text-[var(--muted)]'
            }
          >
            {activeRun.status === 'processing'
              ? 'Processing…'
              : activeRun.status === 'applied'
                ? 'Applied on map'
                : activeRun.status === 'failed'
                  ? 'Could not apply'
                  : 'Selected'}
            {activeRun.message ? ` — ${activeRun.message}` : ''}
          </span>
        </div>
      )}

      {isAdmin && (
        <div className="space-y-2 border-b border-[var(--line)] px-3 py-2">
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md bg-[var(--accent)] px-2.5 py-1.5 text-[11px] font-semibold text-white"
              onClick={() => onOpenAdminTools('upload')}
              data-testid="btn-upload-tool"
            >
              <Upload className="h-3.5 w-3.5" />
              Upload Plugin
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md border border-[var(--line)] px-2.5 py-1.5 text-[11px] font-semibold"
              onClick={() => onOpenAdminTools('tool-tree')}
              data-testid="btn-manage-tree"
            >
              <FolderTree className="h-3.5 w-3.5" />
              Arrange categories
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md border border-[var(--line)] px-2.5 py-1.5 text-[11px] font-semibold"
              onClick={() => onOpenAdminTools('plugins')}
            >
              <Package className="h-3.5 w-3.5" />
              Installed plugins
            </button>
          </div>
          <div className="flex gap-1.5">
            <input
              className="min-w-0 flex-1 rounded border border-[var(--line)] px-2 py-1.5 text-xs"
              placeholder="New head category name…"
              value={newCategoryName}
              onChange={(e) => setNewCategoryName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void createRootCategory();
              }}
              data-testid="inline-new-category"
            />
            <button
              type="button"
              disabled={creating || !newCategoryName.trim()}
              className="inline-flex shrink-0 items-center gap-1 rounded-md border border-[var(--line)] px-2 py-1.5 text-[11px] font-semibold disabled:opacity-50"
              onClick={() => void createRootCategory()}
              data-testid="btn-create-category"
            >
              <FolderPlus className="h-3.5 w-3.5" />
              Add
            </button>
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {loading && <p className="text-xs text-[var(--muted)]">Loading tools…</p>}
        {error && (
          <p className="mb-2 rounded border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-700">
            {error}
          </p>
        )}
        {empty && !error && (
          <div
            className="rounded-lg border border-dashed border-[var(--line)] bg-[var(--bg)] px-3 py-8 text-center"
            data-testid="tools-empty-state"
          >
            <p className="text-sm font-semibold text-[var(--ink)]">No tools installed.</p>
            {isAdmin ? (
              <>
                <p className="mt-2 text-xs text-[var(--muted)]">
                  Use <strong>Upload Plugin</strong> above to install a signed package, or create
                  a head category first. Only administrators can upload, upgrade, or rearrange
                  tools.
                </p>
                <div className="mt-4 flex flex-col items-stretch gap-2 sm:mx-auto sm:max-w-xs">
                  <button
                    type="button"
                    className="rounded-md border border-[var(--line)] bg-white px-3 py-2 text-xs font-semibold"
                    onClick={() => onOpenAdminTools('tool-tree')}
                    data-testid="btn-empty-create-categories"
                  >
                    + Create head / sub categories
                  </button>
                </div>
              </>
            ) : (
              <p className="mt-2 text-xs text-[var(--muted)]">
                Ask an administrator to install and activate tools for your account.
              </p>
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
              onToggleTool={onToggleTool}
              toolRuns={toolRuns}
            />
          ))}
      </div>
    </aside>
  );
}
