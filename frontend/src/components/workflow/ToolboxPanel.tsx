import { useMemo, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  X,
  Compass,
  Layers,
  Image,
  Brain,
  GitCompare,
  Anchor,
  Plane,
  Mountain,
  Shapes,
  Ruler,
  Loader2,
} from 'lucide-react';
import {
  TOOLBOXES,
  type ToolboxId,
  type ToolboxTool,
  type ToolAction,
} from '../../toolbox/catalog';
import type { MapOverlay } from '../../store/workflowStore';
import type { LegendInfo } from '../../services/analyticsService';
import { BufferPanel } from './BufferPanel';

const ICONS: Record<ToolboxId, typeof Compass> = {
  navigation: Compass,
  layers: Layers,
  image: Image,
  ai: Brain,
  change: GitCompare,
  maritime: Anchor,
  aviation: Plane,
  terrain: Mountain,
  gis: Shapes,
  measure: Ruler,
};

interface Props {
  expanded: ToolboxId | null;
  activeToolId: string | null;
  loading: boolean;
  status: string | null;
  overlays: MapOverlay[];
  layerOpacity: number;
  hasScene: boolean;
  hasDrawn: boolean;
  drawnType?: string | null;
  bufferLoading?: boolean;
  lastBufferDistance?: number | null;
  lastBufferArea?: number | null;
  lastLegend?: LegendInfo | null;
  lastMessage?: string | null;
  mapChrome: Record<string, boolean>;
  onExpand: (id: ToolboxId | null) => void;
  onTool: (tool: ToolboxTool) => void;
  onClose: () => void;
  onOpacity: (v: number) => void;
  onToggleOverlay: (id: string) => void;
  onRemoveOverlay: (id: string) => void;
  onMoveOverlay: (id: string, dir: 'up' | 'down') => void;
  onRenameOverlay: (id: string, label: string) => void;
  onApplyBuffer: (distance: number) => void;
  onClearBuffer: () => void;
}

export function ToolboxPanel({
  expanded,
  activeToolId,
  loading,
  status,
  overlays,
  layerOpacity,
  hasScene,
  hasDrawn,
  drawnType,
  bufferLoading,
  lastBufferDistance,
  lastBufferArea,
  lastLegend,
  lastMessage,
  mapChrome,
  onExpand,
  onTool,
  onClose,
  onOpacity,
  onToggleOverlay,
  onRemoveOverlay,
  onMoveOverlay,
  onRenameOverlay,
  onApplyBuffer,
  onClearBuffer,
}: Props) {
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');

  const managedLayers = useMemo(
    () => [...overlays].reverse(),
    [overlays],
  );

  return (
    <aside className="flex h-full min-h-0 w-full flex-col border-l border-[var(--line)] bg-white">
      <div className="flex shrink-0 items-start justify-between gap-2 border-b border-[var(--line)] px-3 py-2.5">
        <div>
          <h2 className="font-display text-base font-semibold">Toolboxes</h2>
          <p className="text-[11px] text-[var(--muted)]">
            Right-side analysis · apply on imagery where available
          </p>
        </div>
        <button type="button" className="ev-btn-ghost p-1" onClick={onClose} title="Close">
          <X className="h-4 w-4" />
        </button>
      </div>

      {(loading || status) && (
        <div className="flex items-center gap-2 border-b border-[var(--line)] bg-[var(--accent-soft)] px-3 py-2 text-[11px] text-[var(--accent)]">
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          <span className="line-clamp-2">{status || 'Running…'}</span>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {TOOLBOXES.map((box) => {
          const Icon = ICONS[box.id];
          const open = expanded === box.id;
          return (
            <div key={box.id} className="border-b border-[var(--line)]">
              <button
                type="button"
                className="flex w-full items-center gap-2 px-3 py-2.5 text-left hover:bg-[var(--accent-soft)]"
                onClick={() => onExpand(open ? null : box.id)}
              >
                {open ? (
                  <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[var(--muted)]" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[var(--muted)]" />
                )}
                <Icon className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-semibold">{box.title}</div>
                  <div className="truncate text-[10px] text-[var(--muted)]">{box.blurb}</div>
                </div>
                <span className="rounded bg-[var(--accent-soft)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--accent)]">
                  {box.tools.length}
                </span>
              </button>

              {open && (
                <div className="space-y-2 px-3 pb-3">
                  {box.id === 'layers' && (
                    <LayerManagerBody
                      layers={managedLayers}
                      layerOpacity={layerOpacity}
                      renameId={renameId}
                      renameValue={renameValue}
                      onOpacity={onOpacity}
                      onToggle={onToggleOverlay}
                      onRemove={onRemoveOverlay}
                      onMove={onMoveOverlay}
                      onStartRename={(id, label) => {
                        setRenameId(id);
                        setRenameValue(label);
                      }}
                      onCommitRename={() => {
                        if (renameId && renameValue.trim()) {
                          onRenameOverlay(renameId, renameValue.trim());
                        }
                        setRenameId(null);
                      }}
                      setRenameValue={setRenameValue}
                    />
                  )}

                  {box.id === 'gis' && (
                    <BufferPanel
                      hasGeometry={hasDrawn}
                      geometryType={drawnType}
                      loading={bufferLoading}
                      lastDistance={lastBufferDistance}
                      lastArea={lastBufferArea}
                      onApply={onApplyBuffer}
                      onClear={onClearBuffer}
                    />
                  )}

                  {box.id === 'navigation' && (
                    <div className="flex flex-wrap gap-1 pb-1">
                      {Object.entries(mapChrome)
                        .filter(([, on]) => on)
                        .map(([k]) => (
                          <span
                            key={k}
                            className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-[10px] text-[var(--accent)]"
                          >
                            {k}
                          </span>
                        ))}
                    </div>
                  )}

                  <div className="grid grid-cols-2 gap-1">
                    {box.tools.map((tool) => {
                      const disabled = Boolean(tool.needsScene && !hasScene) || loading;
                      const active = activeToolId === tool.id;
                      return (
                        <button
                          key={tool.id}
                          type="button"
                          title={
                            tool.needsScene && !hasScene
                              ? 'Show a satellite scene first (eye icon)'
                              : tool.hint || tool.label
                          }
                          disabled={disabled}
                          onClick={() => onTool(tool)}
                          className={`rounded-lg border px-2 py-1.5 text-left text-[11px] font-medium leading-snug ${
                            active
                              ? 'border-[var(--accent)] bg-[var(--accent)] text-white'
                              : 'border-[var(--line)] hover:border-[var(--accent)] hover:bg-[var(--accent-soft)]'
                          } disabled:cursor-not-allowed disabled:opacity-45`}
                        >
                          {tool.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {(lastMessage || lastLegend) && (
        <div className="shrink-0 space-y-1 border-t border-[var(--line)] px-3 py-2">
          {lastMessage && (
            <div className="text-[11px] text-[var(--muted)]">{lastMessage}</div>
          )}
          {lastLegend && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wide text-[var(--muted)]">
                {lastLegend.label}
              </div>
              <div
                className="mt-1 h-2 rounded"
                style={{
                  background: `linear-gradient(90deg, ${lastLegend.stops.map((s) => s.color).join(', ')})`,
                }}
              />
              <div className="mt-0.5 flex justify-between font-mono text-[10px] text-[var(--muted)]">
                <span>{lastLegend.min.toFixed(2)}</span>
                <span>{lastLegend.unit}</span>
                <span>{lastLegend.max.toFixed(2)}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </aside>
  );
}

function LayerManagerBody({
  layers,
  layerOpacity,
  renameId,
  renameValue,
  onOpacity,
  onToggle,
  onRemove,
  onMove,
  onStartRename,
  onCommitRename,
  setRenameValue,
}: {
  layers: MapOverlay[];
  layerOpacity: number;
  renameId: string | null;
  renameValue: string;
  onOpacity: (v: number) => void;
  onToggle: (id: string) => void;
  onRemove: (id: string) => void;
  onMove: (id: string, dir: 'up' | 'down') => void;
  onStartRename: (id: string, label: string) => void;
  onCommitRename: () => void;
  setRenameValue: (v: string) => void;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-[var(--line)] bg-[var(--bg)] p-2">
      <label className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-[var(--muted)]">
        Opacity
        <input
          type="range"
          min={0}
          max={100}
          value={Math.round(layerOpacity * 100)}
          onChange={(e) => onOpacity(Number(e.target.value) / 100)}
          className="w-full accent-[var(--accent)]"
        />
        <span className="w-8 font-mono">{Math.round(layerOpacity * 100)}%</span>
      </label>
      {layers.length === 0 && (
        <div className="text-[11px] text-[var(--muted)]">No layers yet — open a scene eye.</div>
      )}
      {layers.map((layer, idx) => (
        <div
          key={layer.id}
          className="rounded border border-[var(--line)] bg-white px-2 py-1.5 text-[11px]"
        >
          <div className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={layer.visible !== false}
              onChange={() => onToggle(layer.id)}
              title="Visibility"
            />
            {renameId === layer.id ? (
              <input
                className="ev-input flex-1 py-0.5 text-[11px]"
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onBlur={onCommitRename}
                onKeyDown={(e) => e.key === 'Enter' && onCommitRename()}
                autoFocus
              />
            ) : (
              <button
                type="button"
                className="flex-1 truncate text-left font-medium"
                onDoubleClick={() => onStartRename(layer.id, layer.label)}
                title="Double-click to rename"
              >
                {layer.label}
              </button>
            )}
            <span className="rounded bg-[var(--accent-soft)] px-1 text-[9px] uppercase text-[var(--accent)]">
              {layer.kind}
            </span>
          </div>
          <div className="mt-1 flex gap-1">
            <button
              type="button"
              className="ev-btn-ghost px-1.5 py-0.5 text-[10px]"
              disabled={idx === 0}
              onClick={() => onMove(layer.id, 'up')}
            >
              Up
            </button>
            <button
              type="button"
              className="ev-btn-ghost px-1.5 py-0.5 text-[10px]"
              disabled={idx === layers.length - 1}
              onClick={() => onMove(layer.id, 'down')}
            >
              Down
            </button>
            <button
              type="button"
              className="ev-btn-ghost px-1.5 py-0.5 text-[10px]"
              onClick={() => onStartRename(layer.id, layer.label)}
            >
              Rename
            </button>
            <button
              type="button"
              className="ev-btn-ghost px-1.5 py-0.5 text-[10px] text-red-600"
              onClick={() => onRemove(layer.id)}
            >
              Remove
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

export type { ToolAction };
