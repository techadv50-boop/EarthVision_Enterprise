import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowDown,
  ArrowUp,
  FolderPlus,
  FolderTree,
  Save,
  Trash2,
} from 'lucide-react';
import { pluginService } from '../../services/pluginService';
import {
  toolTreeService,
  type ToolCategoryNode,
  type ToolPlacementNode,
} from '../../services/toolTreeService';
import { PluginInstallWizard } from './PluginInstallWizard';

type Mode = 'tree' | 'upload';

interface Props {
  initialMode?: Mode;
}

function flatten(
  nodes: ToolCategoryNode[],
  prefix = '',
): Array<{ id: string; label: string; node: ToolCategoryNode }> {
  const out: Array<{ id: string; label: string; node: ToolCategoryNode }> = [];
  for (const n of nodes) {
    const label = prefix ? `${prefix} / ${n.name}` : n.name;
    out.push({ id: n.id, label, node: n });
    out.push(...flatten(n.children || [], label));
  }
  return out;
}

export function ToolTreeManagerSection({ initialMode = 'tree' }: Props) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [tree, setTree] = useState<Awaited<ReturnType<typeof toolTreeService.getManageTree>> | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [newRootName, setNewRootName] = useState('');
  const [newChildName, setNewChildName] = useState('');
  const [selectedCategoryId, setSelectedCategoryId] = useState<string>('');
  const [selectedPlacement, setSelectedPlacement] = useState<ToolPlacementNode | null>(null);
  const [moveTargetCategory, setMoveTargetCategory] = useState('');

  const refresh = useCallback(async () => {
    const data = await toolTreeService.getManageTree();
    setTree(data);
  }, []);

  useEffect(() => {
    refresh().catch((err: unknown) =>
      setError(err instanceof Error ? err.message : 'Failed to load tool tree'),
    );
  }, [refresh]);

  const flat = useMemo(() => flatten(tree?.roots || []), [tree]);

  async function run(label: string, fn: () => Promise<Record<string, unknown>>) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await fn();
      if (res.ok === false) setError(String(res.error || `${label} failed`));
      else setMessage(`${label} OK`);
      await refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : `${label} failed`);
    } finally {
      setBusy(false);
    }
  }

  const siblingsFor = (parentId: string | null) => {
    if (!tree) return [];
    if (parentId == null) return tree.roots;
    const found = flat.find((f) => f.id === parentId);
    return found?.node.children || [];
  };

  async function moveCategoryOrder(categoryId: string, parentId: string | null, dir: -1 | 1) {
    const sibs = siblingsFor(parentId);
    const ids = sibs.map((s) => s.id);
    const idx = ids.indexOf(categoryId);
    if (idx < 0) return;
    const j = idx + dir;
    if (j < 0 || j >= ids.length) return;
    const next = [...ids];
    [next[idx], next[j]] = [next[j], next[idx]];
    await run('Reorder categories', () => toolTreeService.reorderCategories(next, parentId));
  }

  async function moveToolOrder(placement: ToolPlacementNode, dir: -1 | 1) {
    const cat = flat.find((f) => f.id === placement.category_id)?.node;
    if (!cat) return;
    const ids = cat.placements.map((p) => p.id);
    const idx = ids.indexOf(placement.id);
    if (idx < 0) return;
    const j = idx + dir;
    if (j < 0 || j >= ids.length) return;
    const next = [...ids];
    [next[idx], next[j]] = [next[j], next[idx]];
    await run('Reorder tools', () => toolTreeService.reorderPlacements(placement.category_id, next));
  }

  return (
    <div className="space-y-4" data-testid="tool-tree-manager">
      <div>
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <FolderTree className="h-4 w-4 text-[var(--accent)]" />
          Tool Tree Manager
        </h3>
        <p className="mt-1 text-xs text-[var(--muted)]">
          Build unlimited nested categories. Place plugins in the tree independently from where
          their UI opens. Changes persist server-side with audit history. No Host rebuild.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
            mode === 'tree' ? 'bg-[var(--accent)] text-white' : 'border border-[var(--line)]'
          }`}
          onClick={() => setMode('tree')}
        >
          Manage Tool Tree
        </button>
        <button
          type="button"
          className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
            mode === 'upload' ? 'bg-[var(--accent)] text-white' : 'border border-[var(--line)]'
          }`}
          onClick={() => setMode('upload')}
          data-testid="open-upload-wizard"
        >
          Upload Tool Plugin
        </button>
      </div>

      {error && (
        <p className="rounded border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-700">
          {error}
        </p>
      )}
      {message && (
        <p className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-xs text-emerald-800">
          {message}
        </p>
      )}

      {mode === 'upload' && (
        <PluginInstallWizard
          categories={tree?.roots || []}
          onRefreshCategories={async () => {
            await refresh();
          }}
          onDone={() => {
            setMode('tree');
            void refresh();
          }}
        />
      )}

      {mode === 'tree' && (
        <>
          <section className="space-y-2 rounded border border-[var(--line)] p-3">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
              Create category
            </h4>
            <div className="flex flex-wrap gap-2">
              <input
                className="min-w-[12rem] flex-1 rounded border border-[var(--line)] px-2 py-1 text-xs"
                placeholder="Root category name"
                value={newRootName}
                onChange={(e) => setNewRootName(e.target.value)}
                data-testid="new-root-category"
              />
              <button
                type="button"
                disabled={busy || !newRootName.trim()}
                className="inline-flex items-center gap-1 rounded-md bg-[var(--accent)] px-2 py-1 text-xs font-semibold text-white disabled:opacity-50"
                onClick={() =>
                  void run('Create root', async () => {
                    const res = await toolTreeService.createCategory({
                      name: newRootName.trim(),
                    });
                    setNewRootName('');
                    return res;
                  })
                }
                data-testid="create-root-category"
              >
                <FolderPlus className="h-3 w-3" />
                Create root
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              <select
                className="min-w-[12rem] flex-1 rounded border border-[var(--line)] px-2 py-1 text-xs"
                value={selectedCategoryId}
                onChange={(e) => setSelectedCategoryId(e.target.value)}
                data-testid="parent-category-select"
              >
                <option value="">Parent for subcategory…</option>
                {flat.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
              <input
                className="min-w-[10rem] flex-1 rounded border border-[var(--line)] px-2 py-1 text-xs"
                placeholder="Subcategory name"
                value={newChildName}
                onChange={(e) => setNewChildName(e.target.value)}
                data-testid="new-child-category"
              />
              <button
                type="button"
                disabled={busy || !selectedCategoryId || !newChildName.trim()}
                className="rounded-md border border-[var(--line)] px-2 py-1 text-xs font-semibold disabled:opacity-50"
                onClick={() =>
                  void run('Create subcategory', async () => {
                    const res = await toolTreeService.createCategory({
                      name: newChildName.trim(),
                      parent_id: selectedCategoryId,
                    });
                    setNewChildName('');
                    return res;
                  })
                }
                data-testid="create-child-category"
              >
                Create subcategory
              </button>
            </div>
          </section>

          <section className="space-y-2 rounded border border-[var(--line)] p-3">
            <div className="flex items-center justify-between gap-2">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
                Tree preview
              </h4>
              <button
                type="button"
                disabled={busy}
                className="inline-flex items-center gap-1 rounded-md border border-[var(--line)] px-2 py-1 text-[11px] font-semibold"
                onClick={() =>
                  void run('Snapshot layout', () =>
                    toolTreeService.snapshot(`layout-${new Date().toISOString()}`),
                  )
                }
              >
                <Save className="h-3 w-3" />
                Publish snapshot
              </button>
            </div>
            {tree?.empty && (
              <p className="text-xs text-[var(--muted)]" data-testid="manage-tree-empty">
                No categories yet. Create a root category to begin.
              </p>
            )}
            <ul className="space-y-2 text-xs" data-testid="manage-tree-list">
              {flat.map((c) => (
                <li key={c.id} className="rounded border border-[var(--line)] p-2">
                  <div className="flex flex-wrap items-center gap-1">
                    <span className="font-semibold">{c.label}</span>
                    <button
                      type="button"
                      className="rounded border border-[var(--line)] p-0.5"
                      title="Move up"
                      onClick={() =>
                        void moveCategoryOrder(c.id, c.node.parent_id, -1)
                      }
                    >
                      <ArrowUp className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      className="rounded border border-[var(--line)] p-0.5"
                      title="Move down"
                      onClick={() =>
                        void moveCategoryOrder(c.id, c.node.parent_id, 1)
                      }
                    >
                      <ArrowDown className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      className="ml-auto inline-flex items-center gap-0.5 rounded border border-red-200 px-1.5 py-0.5 text-[10px] text-red-700"
                      onClick={() =>
                        void run('Delete category', () => toolTreeService.deleteCategory(c.id))
                      }
                    >
                      <Trash2 className="h-3 w-3" />
                      Delete if empty
                    </button>
                  </div>
                  <ul className="mt-1 space-y-1 pl-2">
                    {c.node.placements.map((p) => (
                      <li
                        key={p.id}
                        className={`flex flex-wrap items-center gap-1 rounded px-1 py-0.5 ${
                          selectedPlacement?.id === p.id ? 'bg-[var(--accent-soft)]' : ''
                        }`}
                      >
                        <button
                          type="button"
                          className="text-left font-medium"
                          onClick={() => setSelectedPlacement(p)}
                        >
                          {p.display_name}
                          <span className="ml-1 text-[10px] text-[var(--muted)]">
                            → {p.execution_slot}
                            {p.plugin_active ? ' · active' : ` · ${p.activation_status || 'off'}`}
                          </span>
                        </button>
                        <button
                          type="button"
                          className="rounded border border-[var(--line)] p-0.5"
                          onClick={() => void moveToolOrder(p, -1)}
                        >
                          <ArrowUp className="h-3 w-3" />
                        </button>
                        <button
                          type="button"
                          className="rounded border border-[var(--line)] p-0.5"
                          onClick={() => void moveToolOrder(p, 1)}
                        >
                          <ArrowDown className="h-3 w-3" />
                        </button>
                        {p.plugin_active && (
                          <button
                            type="button"
                            className="rounded border border-amber-200 px-1 text-[10px] text-amber-900"
                            onClick={() =>
                              void run('Disable plugin', () => pluginService.disable(p.plugin_id))
                            }
                          >
                            Disable
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </section>

          {selectedPlacement && (
            <section className="space-y-2 rounded border border-[var(--line)] p-3">
              <h4 className="text-xs font-semibold">Move / reconfigure tool</h4>
              <p className="text-[11px] text-[var(--muted)]">
                {selectedPlacement.display_name} ({selectedPlacement.plugin_id})
              </p>
              <select
                className="w-full rounded border border-[var(--line)] px-2 py-1 text-xs"
                value={moveTargetCategory || selectedPlacement.category_id}
                onChange={(e) => setMoveTargetCategory(e.target.value)}
              >
                {flat.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="rounded-md bg-[var(--accent)] px-2 py-1 text-xs font-semibold text-white"
                  onClick={() =>
                    void run('Move tool', () =>
                      toolTreeService.movePlacement(selectedPlacement.id, {
                        category_id: moveTargetCategory || selectedPlacement.category_id,
                      }),
                    )
                  }
                >
                  Move to category
                </button>
                <select
                  className="rounded border border-[var(--line)] px-2 py-1 text-xs"
                  defaultValue={selectedPlacement.execution_slot}
                  onChange={(e) =>
                    void run('Change slot', () =>
                      toolTreeService.upsertPlacement({
                        plugin_id: selectedPlacement.plugin_id,
                        category_id: selectedPlacement.category_id,
                        display_name: selectedPlacement.display_name,
                        execution_slot: e.target.value,
                        icon: selectedPlacement.icon || undefined,
                        visible: selectedPlacement.visible,
                        enabled: selectedPlacement.enabled,
                      }),
                    )
                  }
                >
                  <option value="left_toolbar">left_toolbar</option>
                  <option value="right_analysis_panel">right_analysis_panel</option>
                  <option value="map_overlay">map_overlay</option>
                  <option value="results_panel">results_panel</option>
                </select>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
