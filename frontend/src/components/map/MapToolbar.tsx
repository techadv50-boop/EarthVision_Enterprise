import {
  MousePointer2,
  Ruler,
  Square,
  Pentagon,
  CircleDashed,
  Trash2,
  Camera,
} from 'lucide-react';
import type { MapTool } from '../../store/workflowStore';

const TOOLS: Array<{ id: MapTool; icon: typeof Ruler; label: string; hint: string }> = [
  { id: 'navigate', icon: MousePointer2, label: 'Pan', hint: 'Drag to pan · scroll to zoom' },
  {
    id: 'measure-line',
    icon: Ruler,
    label: 'Distance',
    hint: 'Click points along a path · double-click to reset',
  },
  {
    id: 'measure-area',
    icon: CircleDashed,
    label: 'Area',
    hint: 'Click 3+ vertices · double-click to finish',
  },
  {
    id: 'aoi-rect',
    icon: Square,
    label: 'Rect AOI',
    hint: 'Click two opposite corners',
  },
  {
    id: 'aoi-poly',
    icon: Pentagon,
    label: 'Poly AOI',
    hint: 'Click vertices · double-click to finish',
  },
];

interface Props {
  tool: MapTool;
  measureLabel: string | null;
  layerOpacity: number;
  onTool: (tool: MapTool) => void;
  onOpacity: (v: number) => void;
  onClearAoi: () => void;
  onExportJpeg: () => void;
  hasAoi: boolean;
  exporting?: boolean;
}

export function MapToolbar({
  tool,
  measureLabel,
  layerOpacity,
  onTool,
  onOpacity,
  onClearAoi,
  onExportJpeg,
  hasAoi,
  exporting,
}: Props) {
  return (
    <div className="pointer-events-none absolute inset-x-0 top-3 z-[1000] flex flex-col items-center gap-2 px-3">
      <div className="pointer-events-auto flex flex-wrap items-center justify-center gap-1 rounded-xl border border-[var(--line)] bg-white/95 p-1 shadow-sm">
        {TOOLS.map(({ id, icon: Icon, label, hint }) => (
          <button
            key={id}
            type="button"
            title={hint}
            onClick={() => onTool(id)}
            className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium ${
              tool === id
                ? 'bg-[var(--accent)] text-white'
                : 'text-[var(--muted)] hover:bg-[var(--accent-soft)] hover:text-[var(--accent)]'
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{label}</span>
          </button>
        ))}
        {hasAoi && (
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs text-red-600 hover:bg-red-50"
            onClick={onClearAoi}
          >
            <Trash2 className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Clear</span>
          </button>
        )}
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-lg bg-[#0f2a22] px-2.5 py-1.5 text-xs font-medium text-white hover:brightness-110"
          onClick={onExportJpeg}
          disabled={exporting}
          title="Export map as JPEG (with north arrow, scale, legend, grid)"
        >
          <Camera className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">{exporting ? 'Exporting…' : 'Export JPEG'}</span>
        </button>
      </div>

      <div className="pointer-events-auto flex w-full max-w-sm items-center gap-3 rounded-xl border border-[var(--line)] bg-white/95 px-3 py-2 shadow-sm">
        <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide text-[var(--muted)]">
          Opacity
        </span>
        <input
          type="range"
          min={0}
          max={100}
          value={Math.round(layerOpacity * 100)}
          onChange={(e) => onOpacity(Number(e.target.value) / 100)}
          className="w-full accent-[var(--accent)]"
        />
        <span className="w-8 text-right font-mono text-[11px] text-[var(--muted)]">
          {Math.round(layerOpacity * 100)}%
        </span>
      </div>

      {measureLabel && (
        <div className="pointer-events-auto rounded-full border border-[var(--line)] bg-white/95 px-3 py-1 text-xs font-medium shadow-sm">
          {measureLabel}
        </div>
      )}
    </div>
  );
}
