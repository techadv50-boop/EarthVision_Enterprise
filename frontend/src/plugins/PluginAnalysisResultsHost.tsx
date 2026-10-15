import { usePluginHost } from './PluginHostContext';

/**
 * Host-owned results chrome fed by Host SDK ``host.setAnalysisResult``.
 * Plugins never touch Leaflet or privileged React trees — only publish typed results.
 */
export function PluginAnalysisResultsHost({ className }: { className?: string }) {
  const { analysisByPlugin } = usePluginHost();
  const entries = Object.values(analysisByPlugin);
  if (!entries.length) return null;

  return (
    <div className={className} data-plugin-results-host="1">
      <h3 className="px-3 pt-3 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
        Plugin analysis results
      </h3>
      <ul className="space-y-2 p-3">
        {entries.map((e) => (
          <li
            key={e.pluginId}
            className="rounded border border-[var(--line)] bg-[var(--bg)] p-2 text-xs"
          >
            <div className="font-semibold text-[var(--text)]">
              {e.title || e.pluginId}{' '}
              <span className="font-mono font-normal text-[var(--muted)]">@{e.version}</span>
            </div>
            {e.summary && <p className="mt-1 text-[var(--text)]">{e.summary}</p>}
            {e.metrics && e.metrics.length > 0 && (
              <ul className="mt-2 space-y-1">
                {e.metrics.map((m) => (
                  <li key={m.label} className="flex justify-between font-mono text-[10px]">
                    <span>{m.label}</span>
                    <span>{m.value}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-1 text-[10px] text-[var(--muted)]">{e.updatedAt}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
