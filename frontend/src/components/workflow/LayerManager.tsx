import { useState } from 'react';
import type { MapOverlay } from '../../store/workflowStore';
import {
  DEM_COLORMAPS,
  type DemColormapId,
} from '../../map/DemTerrainLayer';

export function DemBaseHeightPanel({
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
        Run <strong>DEM under imagery</strong> after Eye-On a scene. DEM stays behind the satellite;
        pick a color theme to see elevation.
      </p>
    );
  }
  const baseH = dem.exaggeration ?? 2.0;
  const yaw = dem.demYaw ?? 18;
  const pitch = dem.demPitch ?? 72;
  const cmap = (dem.demColormap as DemColormapId) || 'elev';
  const mix = Math.round((dem.demTextureMix ?? 0.15) * 100);
  const relief = dem.demStats?.relief_m;
  return (
    <div className="mb-3 space-y-1.5 rounded-lg border border-[var(--accent)]/40 bg-[var(--accent-soft)]/40 p-2">
      <div className="text-[11px] font-semibold text-[var(--accent)]">DEM · behind imagery</div>
      <p className="text-[10px] text-[var(--muted)]">
        Color themes show elevation under the satellite
        {relief != null ? ` · relief ${Math.round(relief)} m` : ''}. Manage priority in{' '}
        <strong>Layer Manager</strong>.
      </p>

      <div className="text-[10px] font-semibold text-[var(--ink)]">Color theme</div>
      <div className="grid grid-cols-2 gap-1">
        {DEM_COLORMAPS.map((cm) => (
          <button
            key={cm.id}
            type="button"
            title={cm.label}
            onClick={() => onPatch(dem.id, { demColormap: cm.id })}
            className={`rounded border px-1.5 py-1 text-left text-[10px] ${
              cmap === cm.id
                ? 'border-[var(--accent)] bg-white ring-1 ring-[var(--accent)]'
                : 'border-[var(--line)] bg-white hover:border-[var(--accent)]'
            }`}
          >
            <div className="mb-0.5 h-2 rounded" style={{ background: cm.gradient }} />
            {cm.label}
          </button>
        ))}
      </div>

      <label className="flex items-center gap-2 text-[10px]">
        <span className="w-14 shrink-0 font-medium">Opacity</span>
        <input
          type="range"
          min={20}
          max={100}
          step={1}
          value={Math.round((dem.opacity ?? 0.92) * 100)}
          onChange={(e) => onPatch(dem.id, { opacity: Number(e.target.value) / 100 })}
          className="w-full accent-[var(--accent)]"
        />
        <span className="w-10 font-mono">{Math.round((dem.opacity ?? 0.92) * 100)}%</span>
      </label>
      <label className="flex items-center gap-2 text-[10px]">
        <span className="w-14 shrink-0 font-medium">Sat mix</span>
        <input
          type="range"
          min={0}
          max={50}
          step={1}
          value={mix}
          onChange={(e) => onPatch(dem.id, { demTextureMix: Number(e.target.value) / 100 })}
          className="w-full accent-[var(--accent)]"
          title="Blend a little satellite tint into the elev theme"
        />
        <span className="w-10 font-mono">{mix}%</span>
      </label>
      <label className="flex items-center gap-2 text-[10px]">
        <span className="w-14 shrink-0 font-medium">Height</span>
        <input
          type="range"
          min={8}
          max={50}
          step={1}
          value={Math.round(baseH * 10)}
          onChange={(e) => onPatch(dem.id, { exaggeration: Number(e.target.value) / 10 })}
          className="w-full accent-[var(--accent)]"
        />
        <span className="w-10 font-mono">{baseH.toFixed(1)}×</span>
      </label>
      <label className="flex items-center gap-2 text-[10px]">
        <span className="w-14 shrink-0 font-medium">Tilt</span>
        <input
          type="range"
          min={25}
          max={90}
          step={1}
          value={pitch}
          onChange={(e) => onPatch(dem.id, { demPitch: Number(e.target.value) })}
          className="w-full accent-[var(--accent)]"
        />
        <span className="w-10 font-mono">{pitch}°</span>
      </label>
      <label className="flex items-center gap-2 text-[10px]">
        <span className="w-14 shrink-0 font-medium">Rotate</span>
        <input
          type="range"
          min={0}
          max={360}
          step={2}
          value={yaw}
          onChange={(e) => onPatch(dem.id, { demYaw: Number(e.target.value) })}
          className="w-full accent-[var(--accent)]"
        />
        <span className="w-10 font-mono">{yaw}°</span>
      </label>
      <div className="flex flex-wrap gap-1">
        {[
          { label: 'Flat', patch: { exaggeration: 1.2, demPitch: 88, demYaw: 0 } },
          { label: 'Oblique', patch: { exaggeration: 2.0, demPitch: 72, demYaw: 18 } },
          { label: 'Steep', patch: { exaggeration: 3.2, demPitch: 48, demYaw: 36 } },
        ].map(({ label, patch }) => (
          <button
            key={label}
            type="button"
            className="rounded border border-[var(--line)] bg-white px-1.5 py-0.5 text-[10px] hover:border-[var(--accent)]"
            onClick={() => onPatch(dem.id, patch)}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function LayerManagerBody({
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

  const priority = (idx: number) => layers.length - idx;

  return (
    <div className="space-y-2 rounded-lg border border-[var(--line)] bg-[var(--bg)] p-2">
      <div>
        <div className="text-[11px] font-semibold text-[var(--ink)]">
          Unified layers · {layers.length}
        </div>
        <p className="text-[10px] text-[var(--muted)]">
          Scenes, DEM, indices, buffers & detections in one list. Drag to set priority (top =
          front). DEM base stays under imagery.
        </p>
      </div>
      <label className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-[var(--muted)]">
        Global opacity
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
        <div className="text-[11px] text-[var(--muted)]">
          No layers yet — Eye-On a scene or run a toolbox tool.
        </div>
      )}
      {layers.map((layer, idx) => {
        const isDem = Boolean(layer.demGrid?.length && layer.terrainRole === 'base');
        const baseH = layer.exaggeration ?? 2.0;
        const yaw = layer.demYaw ?? 18;
        const pitch = layer.demPitch ?? 72;
        const cmap = (layer.demColormap as DemColormapId) || 'elev';
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
                  : isDem
                    ? 'border-[var(--accent)]/50'
                    : 'border-[var(--line)]'
            }`}
          >
            <div className="flex items-center gap-1">
              <span
                className="cursor-grab select-none px-0.5 font-mono text-[12px] text-[var(--muted)] active:cursor-grabbing"
                title="Drag to set priority"
                aria-hidden
              >
                ⋮⋮
              </span>
              <span
                className="w-5 shrink-0 rounded bg-[var(--bg)] text-center font-mono text-[9px] text-[var(--muted)]"
                title="Draw priority (higher = more in front)"
              >
                {priority(idx)}
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
                {isDem ? 'dem base' : layer.kind}
              </span>
            </div>

            <label className="mt-1 flex items-center gap-2 text-[10px] text-[var(--muted)]">
              <span className="w-12 shrink-0">Opacity</span>
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round((layer.opacity ?? 1) * 100)}
                onChange={(e) => onPatch(layer.id, { opacity: Number(e.target.value) / 100 })}
                className="w-full accent-[var(--accent)]"
              />
              <span className="w-8 font-mono text-[var(--ink)]">
                {Math.round((layer.opacity ?? 1) * 100)}%
              </span>
            </label>

            {isDem && (
              <div className="mt-1.5 space-y-1 border-t border-[var(--line)] pt-1.5">
                <div className="grid grid-cols-4 gap-0.5">
                  {DEM_COLORMAPS.map((cm) => (
                    <button
                      key={cm.id}
                      type="button"
                      title={cm.label}
                      onClick={() => onPatch(layer.id, { demColormap: cm.id })}
                      className={`h-3 rounded border ${
                        cmap === cm.id
                          ? 'border-[var(--accent)] ring-1 ring-[var(--accent)]'
                          : 'border-[var(--line)]'
                      }`}
                      style={{ background: cm.gradient }}
                    />
                  ))}
                </div>
                <label className="flex items-center gap-2 text-[10px] text-[var(--muted)]">
                  <span className="w-12 shrink-0 font-semibold text-[var(--ink)]">Height</span>
                  <input
                    type="range"
                    min={8}
                    max={50}
                    step={1}
                    value={Math.round(baseH * 10)}
                    onChange={(e) =>
                      onPatch(layer.id, { exaggeration: Number(e.target.value) / 10 })
                    }
                    className="w-full accent-[var(--accent)]"
                  />
                  <span className="w-9 font-mono text-[var(--ink)]">{baseH.toFixed(1)}×</span>
                </label>
                <label className="flex items-center gap-2 text-[10px] text-[var(--muted)]">
                  <span className="w-12 shrink-0 font-semibold text-[var(--ink)]">Tilt</span>
                  <input
                    type="range"
                    min={25}
                    max={90}
                    step={1}
                    value={pitch}
                    onChange={(e) => onPatch(layer.id, { demPitch: Number(e.target.value) })}
                    className="w-full accent-[var(--accent)]"
                  />
                  <span className="w-9 font-mono text-[var(--ink)]">{pitch}°</span>
                </label>
                <label className="flex items-center gap-2 text-[10px] text-[var(--muted)]">
                  <span className="w-12 shrink-0 font-semibold text-[var(--ink)]">Rotate</span>
                  <input
                    type="range"
                    min={0}
                    max={360}
                    step={2}
                    value={yaw}
                    onChange={(e) => onPatch(layer.id, { demYaw: Number(e.target.value) })}
                    className="w-full accent-[var(--accent)]"
                  />
                  <span className="w-9 font-mono text-[var(--ink)]">{yaw}°</span>
                </label>
              </div>
            )}

            <div className="mt-1 flex gap-1">
              <button
                type="button"
                className="ev-btn-ghost px-1.5 py-0.5 text-[10px]"
                disabled={idx === 0 || isDem}
                title={isDem ? 'DEM base stays under imagery' : 'Bring forward'}
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
                className="ev-btn-ghost ml-auto px-1.5 py-0.5 text-[10px] text-red-600"
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
