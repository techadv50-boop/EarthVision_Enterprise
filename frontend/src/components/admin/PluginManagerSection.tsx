import { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  History,
  Package,
  RotateCcw,
  ShieldCheck,
  Upload,
} from 'lucide-react';
import {
  pluginService,
  type PluginAuditEvent,
  type PluginRecord,
  type PluginSystemHealth,
} from '../../services/pluginService';
import { getErrorMessage } from '../../services/api';

function statusBadge(text: string, tone: 'ok' | 'warn' | 'muted' | 'bad') {
  const cls =
    tone === 'ok'
      ? 'bg-emerald-100 text-emerald-800'
      : tone === 'warn'
        ? 'bg-amber-100 text-amber-900'
        : tone === 'bad'
          ? 'bg-red-100 text-red-800'
          : 'bg-[var(--bg)] text-[var(--muted)]';
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${cls}`}>
      {text}
    </span>
  );
}

export function PluginManagerSection() {
  const [plugins, setPlugins] = useState<PluginRecord[]>([]);
  const [audit, setAudit] = useState<PluginAuditEvent[]>([]);
  const [health, setHealth] = useState<PluginSystemHealth | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [versions, setVersions] = useState<
    Array<{ version: string; digest?: string; active?: boolean }>
  >([]);
  const [stagingId, setStagingId] = useState<string | null>(null);
  const [stagingDigest, setStagingDigest] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const [list, hist, h] = await Promise.all([
      pluginService.listAdmin(),
      pluginService.audit(40),
      pluginService.health().catch(() => null),
    ]);
    setPlugins(list.plugins || []);
    setAudit(hist.events || []);
    setHealth(h);
  }, []);

  useEffect(() => {
    refresh().catch((err: unknown) =>
      setError(err instanceof Error ? err.message : 'Failed to load plugins'),
    );
  }, [refresh]);

  useEffect(() => {
    if (!selected) {
      setVersions([]);
      return;
    }
    pluginService
      .versions(selected)
      .then((res) => setVersions(res.versions || []))
      .catch(() => setVersions([]));
  }, [selected, plugins]);

  async function run(label: string, fn: () => Promise<Record<string, unknown>>) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await fn();
      if (res.ok === false) {
        setError(String(res.error || res.detail || `${label} failed`));
      } else {
        setMessage(`${label} OK · ${String(res.plugin_id || '')} ${String(res.version || '')}`.trim());
      }
      await refresh();
    } catch (err: unknown) {
      setError(getErrorMessage(err) || `${label} failed`);
    } finally {
      setBusy(false);
    }
  }

  const selectedPlugin = plugins.find((p) => p.plugin_id === selected) || null;
  const worker = health?.worker;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Package className="h-4 w-4 text-[var(--accent)]" />
          Plugin Manager
        </h3>
        <p className="mt-1 text-xs text-[var(--muted)]">
          Admin only. Uploads use opaque staging IDs. Install does not activate.
          Independent UI loads in a sandboxed iframe via Host SDK — never in the
          privileged React Host Shell. No production secrets in this panel.
        </p>
      </div>

      <section className="space-y-2 rounded border border-[var(--line)] p-3">
        <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
          <Activity className="h-3.5 w-3.5" />
          Subsystem health
        </h4>
        <div className="flex flex-wrap gap-1.5">
          {statusBadge(
            `host sdk ${health?.host_sdk_version || '—'}`,
            health?.host_sdk_version ? 'ok' : 'muted',
          )}
          {statusBadge(
            health?.require_signature ? 'signatures required' : 'signatures off',
            health?.require_signature ? 'ok' : 'warn',
          )}
          {statusBadge(
            `trust ${health?.trust_profile || '—'}`,
            health?.trust_profile ? 'ok' : 'muted',
          )}
          {statusBadge(
            worker?.available
              ? `worker ok${worker.process_isolation ? ` · ${worker.process_isolation}` : ''}`
              : worker?.skipped
                ? 'worker not configured'
                : 'worker unavailable',
            worker?.available ? 'ok' : worker?.skipped ? 'muted' : 'warn',
          )}
          {statusBadge(
            `${health?.active_count ?? 0} active`,
            (health?.active_count || 0) > 0 ? 'ok' : 'muted',
          )}
          {statusBadge(
            health?.loading_model || 'loading model —',
            health?.loading_model ? 'ok' : 'muted',
          )}
        </div>
        {worker?.error && (
          <p className="text-[10px] text-amber-800">Worker: {worker.error}</p>
        )}
      </section>

      {(message || error) && (
        <div
          className={`rounded px-3 py-2 text-xs ${
            error ? 'bg-red-50 text-red-800' : 'bg-emerald-50 text-emerald-900'
          }`}
        >
          {error || message}
        </div>
      )}

      <section className="space-y-2 rounded border border-[var(--line)] p-3">
        <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
          <Upload className="h-3.5 w-3.5" />
          Upload → validate → install (staging ID)
        </h4>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <label className="text-xs text-[var(--muted)]">
            Validate zip
            <input
              type="file"
              accept=".zip,application/zip"
              disabled={busy}
              className="mt-1 block text-xs"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                void run('Validate upload', async () => {
                  const res = await pluginService.validateUpload(file);
                  if (res.ok !== false && res.staging_id && res.digest) {
                    setStagingId(String(res.staging_id));
                    setStagingDigest(String(res.digest));
                  }
                  return res;
                });
              }}
            />
          </label>
        </div>
        {stagingId && (
          <p className="font-mono text-[10px] text-[var(--muted)]">
            staging_id={stagingId}
            {stagingDigest ? ` · digest=${stagingDigest.slice(0, 18)}…` : ''}
          </p>
        )}
        <button
          type="button"
          className="ev-btn text-xs"
          disabled={busy || !stagingId || !stagingDigest}
          onClick={() =>
            void run('Install staging', () =>
              pluginService.installStaging(stagingId!, stagingDigest!),
            )
          }
        >
          Install validated staging (inactive)
        </button>
      </section>

      <section className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
          Installed plugins
        </h4>
        {!plugins.length && (
          <p className="text-xs text-[var(--muted)]">No plugins registered yet.</p>
        )}
        <ul className="divide-y divide-[var(--line)] rounded border border-[var(--line)]">
          {plugins.map((p) => (
            <li
              key={p.plugin_id}
              className={`cursor-pointer px-3 py-2 text-xs hover:bg-[var(--bg)] ${
                selected === p.plugin_id ? 'bg-[var(--bg)]' : ''
              }`}
              onClick={() => setSelected(p.plugin_id)}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-semibold text-[var(--text)]">
                    {p.name || p.plugin_id}{' '}
                    <span className="font-mono font-normal text-[var(--muted)]">
                      @{p.version || '—'}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[10px] text-[var(--muted)]">
                    slot={p.frontend_slot} · host_api={p.compatible_host_api}
                    {p.digest ? ` · ${p.digest.slice(0, 18)}…` : ''}
                  </div>
                </div>
                <div className="flex flex-wrap gap-1">
                  {statusBadge(
                    p.installation_status,
                    p.installation_status === 'installed' ? 'ok' : 'muted',
                  )}
                  {statusBadge(
                    p.activation_status,
                    p.activation_status === 'active' ? 'ok' : 'warn',
                  )}
                  {statusBadge(
                    p.compatible_host_api ? 'compat ok' : 'compat ?',
                    p.compatible_host_api ? 'ok' : 'muted',
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {selectedPlugin && (
        <section className="space-y-2 rounded border border-[var(--line)] p-3">
          <h4 className="flex items-center gap-1.5 text-xs font-semibold">
            <ShieldCheck className="h-3.5 w-3.5" />
            Controls · {selectedPlugin.plugin_id}
          </h4>
          <p className="text-[10px] text-[var(--muted)]">{selectedPlugin.description}</p>
          <div className="flex flex-wrap gap-1.5 text-[10px]">
            {statusBadge(
              `active ${selectedPlugin.version || '—'}`,
              selectedPlugin.activation_status === 'active' ? 'ok' : 'muted',
            )}
            {statusBadge(
              selectedPlugin.digest ? 'digest pinned' : 'no digest',
              selectedPlugin.digest ? 'ok' : 'bad',
            )}
            {statusBadge('signature gate on activate', 'ok')}
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="ev-btn text-xs"
              disabled={busy || selectedPlugin.installation_status !== 'installed'}
              onClick={() =>
                void run('Activate', () =>
                  pluginService.activate(
                    selectedPlugin.plugin_id,
                    selectedPlugin.version || '1.0.0',
                  ),
                )
              }
            >
              Activate
            </button>
            <button
              type="button"
              className="ev-btn-ghost text-xs"
              disabled={busy}
              onClick={() =>
                void run('Disable', () => pluginService.disable(selectedPlugin.plugin_id))
              }
            >
              Disable
            </button>
            <button
              type="button"
              className="ev-btn-ghost text-xs"
              disabled={busy}
              onClick={() =>
                void run('Rollback inactive', () =>
                  pluginService.rollback(selectedPlugin.plugin_id, 'inactive'),
                )
              }
            >
              <RotateCcw className="mr-1 inline h-3 w-3" />
              Rollback → inactive
            </button>
            {selectedPlugin.previous_version && (
              <button
                type="button"
                className="ev-btn-ghost text-xs"
                disabled={busy}
                onClick={() =>
                  void run('Rollback prior', () =>
                    pluginService.rollback(
                      selectedPlugin.plugin_id,
                      selectedPlugin.previous_version || 'inactive',
                    ),
                  )
                }
              >
                Rollback → {selectedPlugin.previous_version}
              </button>
            )}
          </div>

          <div>
            <h5 className="mb-1 text-[10px] font-semibold uppercase text-[var(--muted)]">
              Version history
            </h5>
            <ul className="space-y-1 font-mono text-[10px]">
              {versions.map((v) => (
                <li key={v.version} className="flex items-center justify-between gap-2">
                  <span>
                    {v.version}
                    {v.active ? ' (active)' : ''}
                    {v.digest ? ` · ${v.digest.slice(0, 14)}…` : ''}
                  </span>
                  <button
                    type="button"
                    className="ev-btn-ghost px-2 py-0.5"
                    disabled={busy}
                    onClick={() =>
                      void run(`Activate ${v.version}`, () =>
                        pluginService.activate(selectedPlugin.plugin_id, v.version),
                      )
                    }
                  >
                    Activate
                  </button>
                </li>
              ))}
              {!versions.length && (
                <li className="text-[var(--muted)]">No immutable artifacts on volume yet.</li>
              )}
            </ul>
          </div>
        </section>
      )}

      <section className="space-y-2">
        <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
          <History className="h-3.5 w-3.5" />
          Audit history
        </h4>
        <div className="max-h-48 overflow-y-auto rounded border border-[var(--line)] bg-[var(--bg)] p-2 font-mono text-[10px]">
          {!audit.length && <p className="text-[var(--muted)]">No plugin audit events.</p>}
          {audit.map((ev, i) => (
            <div key={`${ev.ts}-${i}`} className="border-b border-[var(--line)] py-1 last:border-0">
              <span className="text-[var(--muted)]">{ev.ts}</span> {ev.action}{' '}
              {ev.plugin_id}
              {ev.version ? `@${ev.version}` : ''} {ev.ok === false ? `ERR ${ev.error}` : 'OK'}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
