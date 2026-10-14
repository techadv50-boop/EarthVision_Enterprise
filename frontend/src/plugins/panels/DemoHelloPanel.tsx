import { useEffect, useState } from 'react';
import { pluginService } from '../../services/pluginService';
import type { HostPluginComponentProps } from '../slotRegistry';

interface SyntheticPayload {
  message?: string;
  points?: Array<{ label: string; value: number }>;
  note?: string;
  version?: string;
}

export function DemoHelloPanel({ pluginId, version, name }: HostPluginComponentProps) {
  const [payload, setPayload] = useState<SyntheticPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    pluginService
      .synthetic(pluginId)
      .then((res) => {
        if (cancelled) return;
        const body = (res.payload || res) as SyntheticPayload;
        setPayload(body);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load demo plugin');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [pluginId, version]);

  return (
    <div className="border-t border-[var(--line)] p-3">
      <h3 className="text-sm font-semibold text-[var(--text)]">{name}</h3>
      <p className="mt-0.5 text-[10px] text-[var(--muted)]">
        Plugin slot · right analysis panel · v{version || '—'}
      </p>
      {loading && <p className="mt-2 text-xs text-[var(--muted)]">Loading synthetic data…</p>}
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      {payload && (
        <div className="mt-2 space-y-2 text-xs">
          <p className="text-[var(--text)]">{payload.message}</p>
          <ul className="space-y-1">
            {(payload.points || []).map((p) => (
              <li
                key={p.label}
                className="flex justify-between rounded bg-[var(--bg)] px-2 py-1"
              >
                <span>{p.label}</span>
                <span className="font-mono">{p.value}</span>
              </li>
            ))}
          </ul>
          {payload.note && (
            <p className="text-[10px] text-[var(--muted)]">{payload.note}</p>
          )}
        </div>
      )}
    </div>
  );
}
