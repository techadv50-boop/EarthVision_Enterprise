import { useCallback, useEffect, useState } from 'react';
import { FolderOpen, Loader2, Plus, Trash2 } from 'lucide-react';
import {
  folderRepoService,
  type FolderRepoAdmin,
  type FolderRepoCreatePayload,
} from '../../services/folderRepoService';
import { getErrorMessage } from '../../services/api';

const emptyForm: FolderRepoCreatePayload = {
  label: '',
  repository_url: '',
  api_key: '',
  notes: '',
  enabled: true,
  sort_order: 100,
};

export function FolderRepoAdminSection() {
  const [items, setItems] = useState<FolderRepoAdmin[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<'create' | 'edit'>('create');
  const [form, setForm] = useState<FolderRepoCreatePayload>({ ...emptyForm });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await folderRepoService.listAdmin());
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const resetForm = () => {
    setMode('create');
    setSelectedId(null);
    setForm({ ...emptyForm });
    setMessage(null);
    setError(null);
  };

  const selectItem = (row: FolderRepoAdmin) => {
    setMode('edit');
    setSelectedId(row.id);
    setForm({
      label: row.label,
      repository_url: row.repository_url,
      api_key: '',
      notes: row.notes || '',
      enabled: row.enabled,
      sort_order: row.sort_order,
    });
    setMessage(null);
    setError(null);
  };

  const setField = <K extends keyof FolderRepoCreatePayload>(
    key: K,
    value: FolderRepoCreatePayload[K],
  ) => setForm((prev) => ({ ...prev, [key]: value }));

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      if (mode === 'create') {
        await folderRepoService.create({
          ...form,
          notes: form.notes || undefined,
        });
        setMessage(`Added folder repository ${form.label}`);
        resetForm();
      } else if (selectedId) {
        await folderRepoService.update(selectedId, {
          label: form.label,
          repository_url: form.repository_url,
          api_key: form.api_key || undefined,
          notes: form.notes || null,
          enabled: form.enabled,
          sort_order: form.sort_order,
        });
        setMessage(`Updated ${form.label}`);
      }
      await load();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async () => {
    if (!selectedId) return;
    const row = items.find((i) => i.id === selectedId);
    if (!row) return;
    if (!window.confirm(`Remove folder repository "${row.label}"?`)) return;
    setSaving(true);
    setError(null);
    try {
      await folderRepoService.remove(selectedId);
      setMessage(`Removed ${row.label}`);
      resetForm();
      await load();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid gap-4 md:grid-cols-[1fr_1.2fr]" data-testid="folder-repo-admin">
      <section className="rounded-lg border border-[var(--line)] p-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
            Folder repositories
          </h3>
          <button type="button" className="ev-btn-ghost text-xs" onClick={resetForm}>
            <Plus className="mr-1 inline h-3.5 w-3.5" />
            New
          </button>
        </div>
        <p className="mb-2 text-[10px] text-[var(--muted)]">
          Separate from Copernicus satellite APIs. Keys stay on the server and are sent only as{' '}
          <code className="rounded bg-[var(--bg)] px-1">Authorization: Bearer …</code> to
          relay.xdgen.com.
        </p>
        {loading ? (
          <div className="flex items-center gap-2 py-6 text-xs text-[var(--muted)]">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : (
          <ul className="max-h-80 space-y-1 overflow-y-auto">
            {items.map((row) => (
              <li key={row.id}>
                <button
                  type="button"
                  onClick={() => selectItem(row)}
                  className={`w-full rounded-md px-2 py-2 text-left text-sm transition ${
                    selectedId === row.id
                      ? 'bg-[var(--accent-soft)] text-[var(--accent)]'
                      : 'hover:bg-[var(--bg)]'
                  }`}
                >
                  <div className="flex items-center gap-1.5 truncate font-medium">
                    <FolderOpen className="h-3.5 w-3.5 shrink-0" />
                    {row.label}
                  </div>
                  <div className="truncate text-[10px] text-[var(--muted)]">
                    {row.repository_url}
                    {row.has_api_key ? ' · key set' : ' · no key'}
                    {!row.enabled ? ' · disabled' : ''}
                  </div>
                </button>
              </li>
            ))}
            {!items.length && (
              <li className="py-4 text-center text-xs text-[var(--muted)]">
                No folder repositories yet
              </li>
            )}
          </ul>
        )}
      </section>

      <form onSubmit={onSubmit} className="rounded-lg border border-[var(--line)] p-3">
        <h3 className="mb-3 text-sm font-semibold text-[var(--ink)]">
          {mode === 'create' ? 'Add folder repository' : 'Edit folder repository'}
        </h3>
        <p className="mb-3 rounded-md border border-[var(--accent)]/30 bg-[var(--accent-soft)] px-2.5 py-2 text-[11px] text-[var(--ink)]">
          Copy the repository address and API key from the relay Repository card on{' '}
          <strong>relay.xdgen.com</strong>. The key opens only that folder. This is not a
          Copernicus catalog API.
        </p>

        <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
          Display label
        </label>
        <input
          className="ev-input mb-2"
          value={form.label}
          onChange={(e) => setField('label', e.target.value)}
          placeholder="e.g. Raza uploads"
          required
          data-testid="folder-repo-label"
        />

        <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
          Repository address
        </label>
        <input
          className="ev-input mb-2 font-mono text-xs"
          value={form.repository_url}
          onChange={(e) => setField('repository_url', e.target.value)}
          placeholder="https://relay.xdgen.com/api/v1/archives/Raza_uploads"
          required
          data-testid="folder-repo-url"
        />

        <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
          API key {mode === 'edit' ? '(leave blank to keep)' : ''}
        </label>
        <input
          className="ev-input mb-2 font-mono text-xs"
          type="password"
          value={form.api_key}
          onChange={(e) => setField('api_key', e.target.value)}
          required={mode === 'create'}
          autoComplete="new-password"
          placeholder="Folder-scoped key from relay card"
          data-testid="folder-repo-api-key"
        />

        <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">Notes</label>
        <textarea
          className="ev-input mb-2 min-h-[3.5rem] resize-y"
          value={form.notes || ''}
          onChange={(e) => setField('notes', e.target.value)}
        />

        <label className="mb-3 flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={Boolean(form.enabled)}
            onChange={(e) => setField('enabled', e.target.checked)}
          />
          Enabled for clients
        </label>

        {error && (
          <div className="mb-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}
        {message && (
          <div className="mb-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
            {message}
          </div>
        )}

        <div className="flex gap-2">
          <button type="submit" className="ev-btn-primary flex-1" disabled={saving}>
            {saving
              ? 'Saving…'
              : mode === 'create'
                ? 'Add folder repository'
                : 'Save changes'}
          </button>
          {mode === 'edit' && selectedId && (
            <button
              type="button"
              className="ev-btn-ghost px-3 text-red-600"
              onClick={() => void onDelete()}
              disabled={saving}
              title="Delete"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
