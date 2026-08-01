import { useCallback, useEffect, useState } from 'react';
import { Loader2, Plus, Satellite, Trash2 } from 'lucide-react';
import {
  satelliteService,
  type SatelliteAdmin,
  type SatelliteCreatePayload,
} from '../../services/satelliteService';
import { getErrorMessage } from '../../services/api';

const emptyForm: SatelliteCreatePayload = {
  name: '',
  label: '',
  collection_id: '',
  api_base_url: '',
  token_url: '',
  client_id: '',
  auth_username: '',
  auth_password: '',
  notes: '',
  enabled: true,
  sort_order: 100,
};

export function SatelliteAdminSection() {
  const [items, setItems] = useState<SatelliteAdmin[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<'create' | 'edit'>('create');
  const [form, setForm] = useState<SatelliteCreatePayload>({ ...emptyForm });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await satelliteService.listAdmin());
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

  const selectItem = (row: SatelliteAdmin) => {
    setMode('edit');
    setSelectedId(row.id);
    setForm({
      name: row.name,
      label: row.label,
      collection_id: row.collection_id,
      api_base_url: row.api_base_url || '',
      token_url: row.token_url || '',
      client_id: row.client_id || '',
      auth_username: row.auth_username || '',
      auth_password: '',
      notes: row.notes || '',
      enabled: row.enabled,
      sort_order: row.sort_order,
    });
    setMessage(null);
    setError(null);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      if (mode === 'create') {
        await satelliteService.create({
          ...form,
          api_base_url: form.api_base_url || undefined,
          token_url: form.token_url || undefined,
          client_id: form.client_id || undefined,
          auth_username: form.auth_username || undefined,
          auth_password: form.auth_password || undefined,
          notes: form.notes || undefined,
        });
        setMessage(`Added satellite ${form.label}`);
        resetForm();
      } else if (selectedId) {
        await satelliteService.update(selectedId, {
          label: form.label,
          collection_id: form.collection_id,
          api_base_url: form.api_base_url || null,
          token_url: form.token_url || null,
          client_id: form.client_id || null,
          auth_username: form.auth_username || null,
          auth_password: form.auth_password || undefined,
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
    if (!row || row.is_builtin) return;
    if (!window.confirm(`Remove satellite "${row.label}" for all clients?`)) return;
    setSaving(true);
    setError(null);
    try {
      await satelliteService.remove(selectedId);
      setMessage(`Removed ${row.label}`);
      resetForm();
      await load();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const setField = <K extends keyof SatelliteCreatePayload>(
    key: K,
    value: SatelliteCreatePayload[K],
  ) => setForm((prev) => ({ ...prev, [key]: value }));

  return (
    <div className="grid gap-4 md:grid-cols-[1fr_1.2fr]">
      <section className="rounded-lg border border-[var(--line)] p-3">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
            Satellites
          </h3>
          <button type="button" className="ev-btn-ghost text-xs" onClick={resetForm}>
            <Plus className="mr-1 inline h-3.5 w-3.5" />
            New
          </button>
        </div>
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
                    <Satellite className="h-3.5 w-3.5 shrink-0" />
                    {row.label}
                  </div>
                  <div className="truncate text-[10px] text-[var(--muted)]">
                    {row.name} · {row.collection_id}
                    {row.is_builtin ? ' · built-in' : ''}
                    {!row.enabled ? ' · disabled' : ''}
                  </div>
                </button>
              </li>
            ))}
            {!items.length && (
              <li className="py-4 text-center text-xs text-[var(--muted)]">No satellites yet</li>
            )}
          </ul>
        )}
      </section>

      <form onSubmit={onSubmit} className="rounded-lg border border-[var(--line)] p-3">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
          {mode === 'create' ? 'Add satellite API' : 'Edit satellite API'}
        </h3>
        <p className="mb-3 rounded-md border border-[var(--accent)]/30 bg-[var(--accent-soft)] px-2.5 py-2 text-[11px] text-[var(--ink)]">
          Fill the form and click <strong>Add satellite</strong>. The new option appears
          immediately for every client in Find scenes → Satellite.
        </p>

        <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
          Display label
        </label>
        <input
          className="ev-input mb-2"
          value={form.label}
          onChange={(e) => setField('label', e.target.value)}
          placeholder="e.g. Sentinel-3"
          required
        />

        <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
          Satellite key
        </label>
        <input
          className="ev-input mb-2 font-mono text-xs"
          value={form.name}
          onChange={(e) => setField('name', e.target.value)}
          placeholder="e.g. SENTINEL-3"
          required
          disabled={mode === 'edit'}
        />

        <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
          Collection ID (catalog)
        </label>
        <input
          className="ev-input mb-2 font-mono text-xs"
          value={form.collection_id}
          onChange={(e) => setField('collection_id', e.target.value)}
          placeholder="OData / STAC collection name"
          required
        />

        <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
          Catalog API base URL
        </label>
        <input
          className="ev-input mb-2 font-mono text-xs"
          value={form.api_base_url || ''}
          onChange={(e) => setField('api_base_url', e.target.value)}
          placeholder="https://catalogue.dataspace.copernicus.eu/odata/v1"
        />

        <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
          Token URL
        </label>
        <input
          className="ev-input mb-2 font-mono text-xs"
          value={form.token_url || ''}
          onChange={(e) => setField('token_url', e.target.value)}
          placeholder="OAuth token endpoint"
        />

        <div className="mb-2 grid grid-cols-2 gap-2">
          <div>
            <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
              Client ID
            </label>
            <input
              className="ev-input"
              value={form.client_id || ''}
              onChange={(e) => setField('client_id', e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
              Sort order
            </label>
            <input
              className="ev-input"
              type="number"
              value={form.sort_order ?? 100}
              onChange={(e) => setField('sort_order', Number(e.target.value))}
            />
          </div>
        </div>

        <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
          API username
        </label>
        <input
          className="ev-input mb-2"
          value={form.auth_username || ''}
          onChange={(e) => setField('auth_username', e.target.value)}
          autoComplete="off"
        />

        <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">
          API password {mode === 'edit' ? '(leave blank to keep)' : ''}
        </label>
        <input
          className="ev-input mb-2"
          type="password"
          value={form.auth_password || ''}
          onChange={(e) => setField('auth_password', e.target.value)}
          autoComplete="new-password"
        />

        <label className="mb-1 block text-[10px] font-medium text-[var(--muted)]">Notes</label>
        <textarea
          className="ev-input mb-2 min-h-[4rem] resize-y"
          value={form.notes || ''}
          onChange={(e) => setField('notes', e.target.value)}
        />

        <label className="mb-3 flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={Boolean(form.enabled)}
            onChange={(e) => setField('enabled', e.target.checked)}
          />
          Enabled for all clients
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
            {saving ? 'Saving…' : mode === 'create' ? 'Add satellite' : 'Save changes'}
          </button>
          {mode === 'edit' && selectedId && !items.find((i) => i.id === selectedId)?.is_builtin && (
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
