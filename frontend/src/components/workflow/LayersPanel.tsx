import { ArrowDown, ArrowUp, Layers, SplitSquareHorizontal } from 'lucide-react';
import type { MapOverlay } from '../../store/workflowStore';

interface Props {
  overlays: MapOverlay[];
  layerOpacity: number;
  swipeEnabled: boolean;
  onOpacity: (v: number) => void;
  onToggle: (id: string, visible: boolean) => void;
  onMove: (id: string, dir: 'up' | 'down') => void;
  onToggleSwipe: () => void;
}

/** Display order: top of list = top of map (reverse of store bottom→top). */
function displayOrder(overlays: MapOverlay[]): MapOverlay[] {
  return [...overlays].reverse();
}

/**
 * Map layer stack: checkboxes, reorder, opacity, swipe compare.
 * Use after Eye-On + True Color so sharp tiles and processed overlay can be compared.
 */
export function LayersPanel({
  overlays,
  layerOpacity,
  swipeEnabled,
  onOpacity,
  onToggle,
  onMove,
  onToggleSwipe,
}: Props) {
  const layers = displayOrder(overlays);
  if (!overlays.length) return null;

  return (
    <aside
      className="pointer-events-auto absolute bottom-4 left-3 z-[1000] w-[min(18rem,calc(100%-1.5rem))] rounded-xl border border-[var(--line)] bg-white/95 p-2 shadow-lg backdrop-blur-sm"
      data-testid="layers-panel"
    >
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs font-semibold">
          <Layers className="h-3.5 w-3.5 text-[var(--accent)]" />
          Layers
        </div>
        <button
          type="button"
          className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-semibold ${
            swipeEnabled
              ? 'border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]'
              : 'border-[var(--line)] text-[var(--ink)]'
          }`}
          onClick={onToggleSwipe}
          title="Sliding window: compare top layer vs layers below"
          data-testid="layers-swipe-toggle"
        >
          <SplitSquareHorizontal className="h-3 w-3" />
          Swipe
        </button>
      </div>
      <p className="mb-1.5 text-[10px] text-[var(--muted)]">
        Check to show · Up/Down to stack · True Color uses sharp tiles when available
      </p>
      <label className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-[var(--muted)]">
        Opacity
        <input
          type="range"
          min={0}
          max={100}
          value={Math.round(layerOpacity * 100)}
          onChange={(e) => onOpacity(Number(e.target.value) / 100)}
          className="w-full accent-[var(--accent)]"
        />
        <span className="w-8 font-mono normal-case">{Math.round(layerOpacity * 100)}%</span>
      </label>
      <ul className="max-h-48 space-y-1 overflow-y-auto">
        {layers.map((layer, idx) => {
          const checked = layer.visible !== false;
          return (
            <li
              key={layer.id}
              className="flex items-center gap-1 rounded border border-[var(--line)] bg-white px-1.5 py-1 text-[11px]"
              data-testid={`layer-row-${layer.id}`}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={(e) => onToggle(layer.id, e.target.checked)}
                title="Show / hide layer"
              />
              <span className="min-w-0 flex-1 truncate font-medium" title={layer.label}>
                {layer.label}
              </span>
              <span className="rounded bg-[var(--bg)] px-1 text-[9px] uppercase text-[var(--muted)]">
                {layer.kind}
              </span>
              <button
                type="button"
                className="rounded border border-[var(--line)] p-0.5 disabled:opacity-40"
                disabled={idx === 0}
                title="Move up (draw on top)"
                onClick={() => onMove(layer.id, 'up')}
              >
                <ArrowUp className="h-3 w-3" />
              </button>
              <button
                type="button"
                className="rounded border border-[var(--line)] p-0.5 disabled:opacity-40"
                disabled={idx === layers.length - 1}
                title="Move down (draw under)"
                onClick={() => onMove(layer.id, 'down')}
              >
                <ArrowDown className="h-3 w-3" />
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
