import { ArrowLeft, Satellite } from 'lucide-react';
import type { SceneSummary } from '../../services/catalogService';

interface Props {
  placeName: string;
  scenes: SceneSummary[];
  loading: boolean;
  onSelect: (scene: SceneSummary) => void;
  onBack: () => void;
}

function formatDate(value?: string | null): string {
  if (!value) return 'Unknown date';
  try {
    return new Date(value).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return value;
  }
}

function formatSize(bytes?: number | null): string {
  if (!bytes) return '';
  const mb = bytes / (1024 * 1024);
  return mb > 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(0)} MB`;
}

export function ScenesStep({ placeName, scenes, loading, onSelect, onBack }: Props) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3">
        <button type="button" className="ev-btn-ghost mb-1 -ml-2 px-2 py-1 text-xs" onClick={onBack}>
          <ArrowLeft className="h-3.5 w-3.5" /> Change place
        </button>
        <h2 className="font-display text-lg font-semibold">Satellite images</h2>
        <p className="text-sm text-[var(--muted)]">
          20 most recent scenes near <span className="font-medium text-[var(--ink)]">{placeName}</span>
        </p>
      </div>

      {loading && (
        <div className="flex flex-1 items-center justify-center text-sm text-[var(--muted)]">
          Loading scenes…
        </div>
      )}

      {!loading && scenes.length === 0 && (
        <div className="rounded-lg bg-[var(--accent-soft)] p-4 text-sm text-[var(--accent)]">
          No scenes found. Try another place.
        </div>
      )}

      {!loading && scenes.length > 0 && (
        <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
          {scenes.map((scene, i) => (
            <li key={scene.id}>
              <button
                type="button"
                onClick={() => onSelect(scene)}
                className="ev-card flex w-full items-start gap-3 p-3 text-left hover:border-[var(--accent)]"
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--accent-soft)] text-[var(--accent)]">
                  <Satellite className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-[var(--accent)] px-1.5 py-0.5 text-[10px] font-semibold text-white">
                      #{i + 1}
                    </span>
                    <span className="text-xs font-semibold uppercase tracking-wide text-[var(--accent)]">
                      {scene.collection}
                    </span>
                  </div>
                  <div className="mt-1 truncate text-sm font-medium">{scene.name}</div>
                  <div className="mt-1 text-xs text-[var(--muted)]">
                    {formatDate(scene.sensing_time)}
                    {scene.cloud_cover != null && ` · ${scene.cloud_cover}% cloud`}
                    {scene.size_bytes != null && ` · ${formatSize(scene.size_bytes)}`}
                  </div>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
