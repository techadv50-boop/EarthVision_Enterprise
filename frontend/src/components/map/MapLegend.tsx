import type { LegendInfo } from '../../services/analyticsService';

interface Props {
  legend: LegendInfo | null | undefined;
  title?: string;
}

export function MapLegend({ legend, title }: Props) {
  if (!legend) return null;

  const gradient = legend.stops.map((s) => s.color).join(', ');

  return (
    <div className="pointer-events-auto absolute bottom-14 left-3 z-[1000] w-[min(100%-1.5rem,15rem)] rounded-xl border border-[var(--line)] bg-white/95 p-3 shadow-sm">
      <div className="text-xs font-semibold text-[var(--ink)]">
        {title || legend.label}
      </div>
      <div
        className="mt-2 h-2.5 w-full rounded-full"
        style={{ background: `linear-gradient(90deg, ${gradient})` }}
      />
      <div className="mt-1 flex justify-between font-mono text-[10px] text-[var(--muted)]">
        <span>{legend.min.toFixed(2)}</span>
        <span>{legend.unit}</span>
        <span>{legend.max.toFixed(2)}</span>
      </div>
      <p className="mt-2 text-[10px] leading-snug text-[var(--muted)]">{legend.formula}</p>
    </div>
  );
}
