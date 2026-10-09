import { ArrowLeft, Eye, EyeOff, Loader2, Satellite } from 'lucide-react';
import type { SceneSummary } from '../../services/catalogService';

interface Props {
  placeName: string;
  scenes: SceneSummary[];
  visibleSceneIds: string[];
  focusSceneId: string | null;
  loading: boolean;
  loadingOverlayIds: string[];
  satelliteLabel?: string | null;
  dateFrom?: string | null;
  dateTo?: string | null;
  onToggleEye: (scene: SceneSummary) => void;
  onFocus: (scene: SceneSummary) => void;
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

export function ScenesStep({
  placeName,
  scenes,
  visibleSceneIds,
  focusSceneId,
  loading,
  loadingOverlayIds,
  satelliteLabel,
  dateFrom,
  dateTo,
  onToggleEye,
  onFocus,
  onBack,
}: Props) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3">
        <button type="button" className="ev-btn-ghost mb-1 -ml-2 px-2 py-1 text-xs" onClick={onBack}>
          <ArrowLeft className="h-3.5 w-3.5" /> Change satellite / dates
        </button>
        <h2 className="font-display text-lg font-semibold">Satellite images</h2>
        <p className="text-sm text-[var(--muted)]">
          Near <span className="font-medium text-[var(--ink)]">{placeName}</span>
          {' — '}use the eye icon to show or hide imagery on the map.
        </p>
        {(satelliteLabel || (dateFrom && dateTo)) && (
          <p className="mt-1 text-xs text-[var(--muted)]">
            {satelliteLabel && (
              <>
                Satellite:{' '}
                <span className="font-medium text-[var(--ink)]">{satelliteLabel}</span>
              </>
            )}
            {satelliteLabel && dateFrom && dateTo ? ' · ' : null}
            {dateFrom && dateTo && (
              <>
                {formatDate(dateFrom)} → {formatDate(dateTo)}
              </>
            )}
          </p>
        )}
      </div>

      {loading && (
        <div className="flex flex-1 items-center justify-center text-sm text-[var(--muted)]">
          Loading scenes…
        </div>
      )}

      {!loading && scenes.length === 0 && (
        <div className="rounded-lg bg-[var(--accent-soft)] p-4 text-sm text-[var(--accent)]">
          No scenes found for this date range
          {dateFrom && dateTo ? ` (${formatDate(dateFrom)} → ${formatDate(dateTo)})` : ''}.
          Try different From/To dates or another area.
        </div>
      )}

      {!loading && scenes.length > 0 && (
        <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
          {scenes.map((scene, i) => {
            const visible = visibleSceneIds.includes(scene.id);
            const focused = focusSceneId === scene.id;
            const overlayLoading = loadingOverlayIds.includes(scene.id);
            return (
              <li key={scene.id}>
                <div
                  className={`ev-card flex w-full items-start gap-2 p-2.5 ${
                    focused ? 'border-[var(--accent)] ring-1 ring-[var(--accent)]/30' : ''
                  } ${visible ? 'bg-[var(--accent-soft)]/40' : ''}`}
                >
                  <button
                    type="button"
                    className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-[var(--line)] bg-white text-[var(--accent)] hover:bg-[var(--accent-soft)]"
                    title={visible ? 'Hide on map' : 'Show on map'}
                    onClick={() => onToggleEye(scene)}
                    disabled={overlayLoading}
                  >
                    {overlayLoading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : visible ? (
                      <Eye className="h-4 w-4" />
                    ) : (
                      <EyeOff className="h-4 w-4 text-[var(--muted)]" />
                    )}
                  </button>

                  <button
                    type="button"
                    className="min-w-0 flex-1 text-left"
                    onClick={() => {
                      if (visible) onFocus(scene);
                      else onToggleEye(scene);
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-[var(--accent)] px-1.5 py-0.5 text-[10px] font-semibold text-white">
                        #{i + 1}
                      </span>
                      <span className="text-xs font-semibold uppercase tracking-wide text-[var(--accent)]">
                        {scene.collection}
                      </span>
                      {visible && (
                        <span className="rounded bg-teal-600 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-white">
                          on map
                        </span>
                      )}
                    </div>
                    <div className="mt-1 flex items-start gap-1.5">
                      <Satellite className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--muted)]" />
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium">{scene.name}</div>
                        <div className="mt-0.5 text-xs text-[var(--muted)]">
                          {formatDate(scene.sensing_time)}
                        </div>
                      </div>
                    </div>
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
