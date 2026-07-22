import { useEffect, useMemo, useState } from 'react';
import {
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
} from '../../toolbox/catalog';
import type { MapOverlay } from '../../store/workflowStore';
import type { LegendInfo, IndexName, IndexResult, ColormapName } from '../../services/analyticsService';
import type {
  CompositePreset,
  CompositeResult,
  StretchResult,
} from '../../services/compositeService';
import { BufferPanel } from './BufferPanel';
import { ImageProcessingPanel } from './ImageProcessingPanel';
import { detectionService } from '../../services/detectionService';

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

const DEFAULT_CHROME: Record<string, boolean> = {
  compass: true,
  scaleBar: true,
  coordinates: true,
  grid: true,
};

interface Props {
  expanded: ToolboxId | null;
  activeToolId: string | null;
  loading: boolean;
  status: string | null;
  overlays: MapOverlay[];
  layerOpacity: number;
  hasScene: boolean;
  /** When false, category tabs + tools are inactive until a scene is selected */
  toolsEnabled?: boolean;
  /** Optional label for the active scene collection (e.g. SENTINEL-2) */
  sceneCollection?: string | null;
  hasDrawn: boolean;
  drawnType?: string | null;
  bufferLoading?: boolean;
  lastBufferDistance?: number | null;
  lastBufferArea?: number | null;
  lastLegend?: LegendInfo | null;
  lastMessage?: string | null;
  mapChrome?: Record<string, boolean> | null;
  /** null/undefined = all toolboxes; otherwise filter to these ids */
  allowedTools?: string[] | null;
  onExpand: (id: ToolboxId) => void;
  onTool: (tool: ToolboxTool) => void;
  onClose: () => void;
  onOpacity: (v: number) => void;
  onToggleOverlay: (id: string) => void;
  onRemoveOverlay: (id: string) => void;
  onMoveOverlay: (id: string, dir: 'up' | 'down') => void;
  onReorderOverlays?: (displayIds: string[]) => void;
  onPatchOverlay?: (id: string, patch: Partial<MapOverlay>) => void;
  onRenameOverlay: (id: string, label: string) => void;
  onApplyBuffer: (distance: number) => void;
  onClearBuffer: () => void;
  // Image processing
  indexResult?: IndexResult | null;
  compositeResult?: CompositeResult | null;
  stretchResult?: StretchResult | null;
  stretchParams?: {
    p_low: number;
    p_high: number;
    gamma: number;
    brightness: number;
    contrast: number;
  };
  colormap?: ColormapName | string | null;
  onComposite?: (preset: CompositePreset) => void;
  onIndexTool?: (index: IndexName) => void;
  onColormapChange?: (cmap: ColormapName) => void;
  onStretch?: () => void;
  onStretchParams?: (patch: Record<string, number>) => void;
  onEnhance?: (op: 'brightness' | 'contrast' | 'gamma' | 'sharpen' | 'denoise') => void;
  onExportIndexPng?: () => void;
  onExportIndexCsv?: () => void;
  onExportCompositePng?: () => void;
  onExportStretchPng?: () => void;
  onExportOverlayPng?: () => void;
}

export function ToolboxPanel({
  expanded,
  activeToolId,
  loading,
  status,
  overlays,
  layerOpacity,
  hasScene,
  toolsEnabled = true,
  sceneCollection = null,
  hasDrawn,
  drawnType,
  bufferLoading,
  lastBufferDistance,
  lastBufferArea,
  lastLegend,
  lastMessage,
  mapChrome,
  allowedTools = null,
  onExpand,
  onTool,
  onClose,
  onOpacity,
  onToggleOverlay,
  onRemoveOverlay,
  onMoveOverlay,
  onReorderOverlays,
  onPatchOverlay,
  onRenameOverlay,
  onApplyBuffer,
  onClearBuffer,
  indexResult = null,
  compositeResult = null,
  stretchResult = null,
  stretchParams = { p_low: 2, p_high: 98, gamma: 1, brightness: 1, contrast: 1 },
  colormap = null,
  onComposite,
  onIndexTool,
  onColormapChange,
  onStretch,
  onStretchParams,
  onEnhance,
  onExportIndexPng,
  onExportIndexCsv,
  onExportCompositePng,
  onExportStretchPng,
  onExportOverlayPng,
}: Props) {
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [algoByTask, setAlgoByTask] = useState<Record<string, string>>({});

  const visibleToolboxes = useMemo(() => {
    if (allowedTools == null) return TOOLBOXES;
    const allowed = new Set(allowedTools);
    return TOOLBOXES.filter((b) => allowed.has(b.id));
  }, [allowedTools]);

  const activeId = (expanded && visibleToolboxes.some((b) => b.id === expanded)
    ? expanded
    : visibleToolboxes[0]?.id) || 'image';
  const activeBox = visibleToolboxes.find((b) => b.id === activeId) || visibleToolboxes[0] || TOOLBOXES[2];
  const chrome = mapChrome || DEFAULT_CHROME;

  const managedLayers = useMemo(() => [...overlays].reverse(), [overlays]);

  // Ensure a category is always selected from the allowed set
  useEffect(() => {
    if (!visibleToolboxes.length) return;
    if (!expanded || !visibleToolboxes.some((b) => b.id === expanded)) {
      onExpand(visibleToolboxes[0].id);
    }
  }, [expanded, onExpand, visibleToolboxes]);

  // Load algorithm labels for AI / maritime / aviation detection tools
  useEffect(() => {
    if (!['ai', 'maritime', 'aviation'].includes(activeId)) return;
    let cancelled = false;
    detectionService
      .listTasks()
      .then((tasks) => {
        if (cancelled) return;
        const map: Record<string, string> = {};
        for (const t of tasks) {
          if (t.algorithm) map[t.id] = t.algorithm;
        }
        setAlgoByTask(map);
      })
      .catch(() => {
        /* offline / unauth — keep empty */
      });
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  return (
    <aside
      className="flex h-full min-h-[50vh] w-full min-w-[20rem] flex-col border-l-2 border-[var(--accent)] bg-white shadow-sm"
      data-testid="toolbox-panel"
    >
      <div className="flex shrink-0 items-start justify-between gap-2 border-b border-[var(--line)] bg-[var(--accent-soft)] px-3 py-2.5">
        <div>
          <h2 className="font-display text-base font-semibold text-[var(--accent)]">
            Toolboxes
          </h2>
          <p className="text-[11px] text-[var(--muted)]">
            {visibleToolboxes.length} categories ·{' '}
            {visibleToolboxes.reduce((n, b) => n + b.tools.length, 0)} tools
          </p>
        </div>
        <button type="button" className="ev-btn-ghost p-1" onClick={onClose} title="Close">
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Category tabs — inactive until a satellite image is selected */}
      <div className="shrink-0 border-b border-[var(--line)] bg-white px-2 py-2">
        <div className="grid grid-cols-5 gap-1">
          {visibleToolboxes.map((box) => {
            const Icon = ICONS[box.id];
            const on = activeId === box.id;
            return (
              <button
                key={box.id}
                type="button"
                title={
                  toolsEnabled
                    ? box.title
                    : `${box.title} (select a satellite image first)`
                }
                disabled={!toolsEnabled}
                onClick={() => toolsEnabled && onExpand(box.id)}
                className={`flex flex-col items-center gap-0.5 rounded-lg px-1 py-1.5 text-[9px] font-semibold leading-tight ${
                  !toolsEnabled
                    ? 'cursor-not-allowed bg-[var(--bg)] text-[var(--muted)] opacity-50'
                    : on
                      ? 'bg-[var(--accent)] text-white'
                      : 'bg-[var(--bg)] text-[var(--muted)] hover:bg-[var(--accent-soft)] hover:text-[var(--accent)]'
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                <span className="line-clamp-2 w-full text-center">
                  {box.title.split(' ')[0]}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {!toolsEnabled && (
        <div className="border-b border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-900">
          Toolboxes are inactive. Eye-On a satellite image in the catalog to unlock tools for
          that mission
          {sceneCollection ? ` (${sceneCollection})` : ''}.
        </div>
      )}

      {toolsEnabled && sceneCollection && (
        <div className="border-b border-[var(--line)] bg-[var(--bg)] px-3 py-1.5 text-[10px] text-[var(--muted)]">
          Active for <span className="font-semibold text-[var(--ink)]">{sceneCollection}</span>
          {' — '}
          tools match this image only
        </div>
      )}

      {(loading || status) && (
        <div className="flex items-center gap-2 border-b border-[var(--line)] bg-[var(--accent-soft)] px-3 py-2 text-[11px] text-[var(--accent)]">
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          <span className="line-clamp-2">{status || 'Running…'}</span>
        </div>
      )}

      <div
        className={`min-h-0 flex-1 overflow-y-auto p-3 ${!toolsEnabled ? 'pointer-events-none opacity-50' : ''}`}
      >
        <div className="mb-2">
          <div className="font-display text-sm font-semibold">{activeBox.title}</div>
          <p className="text-[11px] text-[var(--muted)]">{activeBox.blurb}</p>
          {['ai', 'maritime', 'aviation'].includes(activeBox.id) && (
            <p className="mt-1 rounded border border-[var(--line)] bg-[var(--bg)] px-2 py-1 text-[10px] text-[var(--muted)]">
              ML / neural detectors (MLP built-up buildings, CFAR ships, Hough roads, DoG
              aircraft, RandomForest LULC). Eye-On an optical scene first — no random placeholders.
            </p>
          )}
          {!hasScene && (
            <p className="mt-1 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[10px] text-amber-800">
              Select a place and toggle a scene eye to activate tools for that satellite image.
            </p>
          )}
        </div>

        {activeBox.id === 'image' && onComposite && onIndexTool && onStretch && (
          <ImageProcessingPanel
            hasScene={hasScene && toolsEnabled}
            loading={loading}
            activeToolId={activeToolId}
            indexResult={indexResult}
            compositeResult={compositeResult}
            stretchResult={stretchResult}
            stretchParams={stretchParams}
            colormap={colormap}
            onComposite={onComposite}
            onIndex={onIndexTool}
            onColormapChange={onColormapChange}
            onStretch={onStretch}
            onStretchParams={(patch) => onStretchParams?.(patch)}
            onEnhance={(op) => onEnhance?.(op)}
            onExportIndexPng={() => onExportIndexPng?.()}
            onExportIndexCsv={() => onExportIndexCsv?.()}
            onExportCompositePng={() => onExportCompositePng?.()}
            onExportStretchPng={() => onExportStretchPng?.()}
            onExportOverlayPng={() => onExportOverlayPng?.()}
          />
        )}

        {activeBox.id === 'layers' && (
          <div className="mb-3">
            <LayerManagerBody
              layers={managedLayers}
              layerOpacity={layerOpacity}
              renameId={renameId}
              renameValue={renameValue}
              onOpacity={onOpacity}
              onToggle={onToggleOverlay}
              onRemove={onRemoveOverlay}
              onMove={onMoveOverlay}
              onReorder={(ids) => onReorderOverlays?.(ids)}
              onPatch={(id, patch) => onPatchOverlay?.(id, patch)}
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
          </div>
        )}

        {activeBox.id === 'gis' && (
          <div className="mb-3">
            <BufferPanel
              hasGeometry={hasDrawn}
              geometryType={drawnType}
              loading={bufferLoading}
              lastDistance={lastBufferDistance}
              lastArea={lastBufferArea}
              onApply={onApplyBuffer}
              onClear={onClearBuffer}
            />
          </div>
        )}

        {activeBox.id === 'navigation' && (
          <div className="mb-2 flex flex-wrap gap-1">
            {Object.entries(chrome)
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

        {activeBox.id === 'terrain' && (
          <DemBaseHeightPanel
            overlays={overlays}
            onPatch={(id, patch) => onPatchOverlay?.(id, patch)}
          />
        )}

        {activeBox.id !== 'image' && (
          <div className="grid grid-cols-2 gap-1" data-testid="toolbox-tool-list">
            {activeBox.tools.map((tool) => {
              const active = activeToolId === tool.id;
              const taskId =
                tool.action.type === 'detection' ? tool.action.task : undefined;
              const algo = taskId ? algoByTask[taskId] : undefined;
              const tip = !toolsEnabled
                ? 'Select a satellite image first'
                : active
                  ? `${tool.label} (click again to turn off)`
                  : algo || tool.hint || tool.label;
              return (
                <button
                  key={tool.id}
                  type="button"
                  title={tip}
                  disabled={loading || !toolsEnabled}
                  onClick={() => onTool(tool)}
                  className={`flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-[12px] font-medium ${
                    active
                      ? 'border-[var(--accent)] bg-[var(--accent)] text-white'
                      : 'border-[var(--line)] bg-white hover:border-[var(--accent)] hover:bg-[var(--accent-soft)]'
                  } disabled:cursor-not-allowed disabled:opacity-50`}
                >
                  <span
                    className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border text-[9px] ${
                      active
                        ? 'border-white/80 bg-white/20'
                        : 'border-[var(--line)] text-[var(--muted)]'
                    }`}
                  >
                    {active ? '✓' : ''}
                  </span>
                  <span className="flex-1">{tool.label}</span>
                  {tool.needsScene && (
                    <span
                      className={`rounded px-1 py-0.5 text-[9px] uppercase ${
                        active ? 'bg-white/20' : 'bg-[var(--bg)] text-[var(--muted)]'
                      }`}
                    >
                      EO
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
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

function DemBaseHeightPanel({
  overlays,
  onPatch,
}: {
  overlays: MapOverlay[];
  onPatch: (id: string, patch: Partial<MapOverlay>) => void;
}) {
  const dem = overlays.find((o) => o.demGrid?.length && o.terrainRole === 'base');
  if (!dem) {
    return (
      <p className="mb-2 rounded border border-[var(--line)] bg-[var(--bg)] px-2 py-1.5 text-[10px] text-[var(--muted)]">
        Run <strong>DEM 3D</strong> to enable base height control. Drag layers in Layer Manager to
        stack DEM under or over imagery.
      </p>
    );
  }
  const baseH = dem.exaggeration ?? 1.2;
  const relief = dem.demStats?.relief_m;
  return (
    <div className="mb-3 space-y-1.5 rounded-lg border border-[var(--accent)]/40 bg-[var(--accent-soft)]/40 p-2">
      <div className="text-[11px] font-semibold text-[var(--accent)]">DEM base height</div>
      <p className="text-[10px] text-[var(--muted)]">
        Vertical scale of the elevation surface under the satellite image
        {relief != null ? ` · relief ${Math.round(relief)} m` : ''}.
      </p>
      <label className="flex items-center gap-2 text-[10px]">
        <span className="shrink-0 font-medium">Base height</span>
        <input
          type="range"
          min={5}
          max={30}
          step={1}
          value={Math.round(baseH * 10)}
          onChange={(e) => onPatch(dem.id, { exaggeration: Number(e.target.value) / 10 })}
          className="w-full accent-[var(--accent)]"
        />
        <span className="w-10 font-mono">{baseH.toFixed(1)}×</span>
      </label>
      <div className="flex gap-1">
        {[0.8, 1.2, 1.8, 2.5].map((v) => (
          <button
            key={v}
            type="button"
            className={`rounded border px-1.5 py-0.5 text-[10px] ${
              Math.abs(baseH - v) < 0.05
                ? 'border-[var(--accent)] bg-[var(--accent)] text-white'
                : 'border-[var(--line)] bg-white'
            }`}
            onClick={() => onPatch(dem.id, { exaggeration: v })}
          >
            {v}×
          </button>
        ))}
      </div>
    </div>
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
  onReorder,
  onPatch,
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
  onReorder: (displayIds: string[]) => void;
  onPatch: (id: string, patch: Partial<MapOverlay>) => void;
  onStartRename: (id: string, label: string) => void;
  onCommitRename: () => void;
  setRenameValue: (v: string) => void;
}) {
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);

  const applyDrop = (targetId: string) => {
    if (!dragId || dragId === targetId) {
      setDragId(null);
      setOverId(null);
      return;
    }
    const ids = layers.map((l) => l.id);
    const from = ids.indexOf(dragId);
    const to = ids.indexOf(targetId);
    if (from < 0 || to < 0) {
      setDragId(null);
      setOverId(null);
      return;
    }
    const next = [...ids];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    onReorder(next);
    setDragId(null);
    setOverId(null);
  };

  return (
    <div className="space-y-2 rounded-lg border border-[var(--line)] bg-[var(--bg)] p-2">
      <p className="text-[10px] text-[var(--muted)]">
        Drag layers to reorder — top of list draws on top of the map.
      </p>
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
      {layers.map((layer, idx) => {
        const isDem = Boolean(layer.demGrid?.length);
        const baseH = layer.exaggeration ?? 1.2;
        return (
          <div
            key={layer.id}
            draggable
            onDragStart={(e) => {
              setDragId(layer.id);
              e.dataTransfer.effectAllowed = 'move';
              e.dataTransfer.setData('text/plain', layer.id);
            }}
            onDragOver={(e) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = 'move';
              if (overId !== layer.id) setOverId(layer.id);
            }}
            onDragLeave={() => {
              if (overId === layer.id) setOverId(null);
            }}
            onDrop={(e) => {
              e.preventDefault();
              applyDrop(layer.id);
            }}
            onDragEnd={() => {
              setDragId(null);
              setOverId(null);
            }}
            className={`rounded border bg-white px-2 py-1.5 text-[11px] ${
              dragId === layer.id
                ? 'border-[var(--accent)] opacity-60'
                : overId === layer.id
                  ? 'border-[var(--accent)] bg-[var(--accent-soft)]'
                  : 'border-[var(--line)]'
            }`}
          >
            <div className="flex items-center gap-1">
              <span
                className="cursor-grab select-none px-0.5 font-mono text-[12px] text-[var(--muted)] active:cursor-grabbing"
                title="Drag to reorder"
                aria-hidden
              >
                ⋮⋮
              </span>
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

            {isDem && (
              <label className="mt-1.5 flex items-center gap-2 text-[10px] text-[var(--muted)]">
                <span className="shrink-0 font-semibold text-[var(--ink)]">Base height</span>
                <input
                  type="range"
                  min={5}
                  max={30}
                  step={1}
                  value={Math.round(baseH * 10)}
                  onChange={(e) =>
                    onPatch(layer.id, { exaggeration: Number(e.target.value) / 10 })
                  }
                  className="w-full accent-[var(--accent)]"
                  title="DEM vertical scale / base height"
                />
                <span className="w-9 font-mono text-[var(--ink)]">{baseH.toFixed(1)}×</span>
              </label>
            )}

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
        );
      })}
    </div>
  );
}
