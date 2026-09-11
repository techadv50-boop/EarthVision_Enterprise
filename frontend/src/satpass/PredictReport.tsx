import { useMemo, useState } from 'react';
import { Download } from 'lucide-react';
import type { PassRow } from './predict/types';
import { durationLabel, formatInZone, formatUtc } from './predict/time';
import { downloadCsv, downloadServerReport, passExportRows } from './predict/export';

type Col = keyof PassRow | 'duration' | 'startLocal' | 'endLocal';

const COLS: { key: Col; label: string }[] = [
  { key: 'passNumber', label: 'Pass #' },
  { key: 'satelliteName', label: 'Satellite Name' },
  { key: 'passDateUtc', label: 'Pass date' },
  { key: 'startLocal', label: 'Start Tracking Time' },
  { key: 'endLocal', label: 'End Tracking Time' },
  { key: 'duration', label: 'Duration' },
  { key: 'maxElevationDeg', label: 'Max elevation' },
  { key: 'maxElevationUtc', label: 'Max elevation time' },
  { key: 'aosUtc', label: 'AOS' },
  { key: 'losUtc', label: 'LOS' },
  { key: 'visibility', label: 'Visibility' },
];

function cell(p: PassRow, key: Col, tz: string): string {
  switch (key) {
    case 'duration':
      return durationLabel(p.durationSec);
    case 'startLocal':
      return `${formatInZone(p.startUtc, tz)}\n${formatUtc(p.startUtc)}`;
    case 'endLocal':
      return `${formatInZone(p.endUtc, tz)}\n${formatUtc(p.endUtc)}`;
    case 'maxElevationDeg':
      return p.maxElevationDeg == null ? '—' : `${p.maxElevationDeg.toFixed(1)}°`;
    case 'maxElevationUtc':
      return p.maxElevationUtc
        ? `${formatInZone(p.maxElevationUtc, tz)}\n${formatUtc(p.maxElevationUtc)}`
        : '—';
    case 'aosUtc':
      return formatUtc(p.aosUtc);
    case 'losUtc':
      return formatUtc(p.losUtc);
    default:
      return String(p[key] ?? '');
  }
}

export default function PredictReport({
  passes,
  timeZone,
}: {
  passes: PassRow[];
  timeZone: string;
}) {
  const [sortKey, setSortKey] = useState<Col>('startLocal');
  const [asc, setAsc] = useState(true);
  const [busy, setBusy] = useState('');

  const sorted = useMemo(() => {
    const copy = [...passes];
    copy.sort((a, b) => {
      const av = cell(a, sortKey, timeZone);
      const bv = cell(b, sortKey, timeZone);
      if (sortKey === 'passNumber' || sortKey === 'maxElevationDeg' || sortKey === 'duration') {
        const an = sortKey === 'duration' ? a.durationSec : Number(a[sortKey as keyof PassRow] ?? 0);
        const bn = sortKey === 'duration' ? b.durationSec : Number(b[sortKey as keyof PassRow] ?? 0);
        return asc ? an - bn : bn - an;
      }
      if (sortKey === 'startLocal') {
        return asc
          ? a.startUtc.localeCompare(b.startUtc)
          : b.startUtc.localeCompare(a.startUtc);
      }
      return asc ? av.localeCompare(bv) : bv.localeCompare(av);
    });
    return copy;
  }, [passes, sortKey, asc, timeZone]);

  const exportData = () => passExportRows(sorted, timeZone);

  const onSort = (key: Col) => {
    if (sortKey === key) setAsc((v) => !v);
    else {
      setSortKey(key);
      setAsc(true);
    }
  };

  const doExport = async (kind: 'csv' | 'xlsx' | 'pdf') => {
    const { headers, rows } = exportData();
    setBusy(kind);
    try {
      if (kind === 'csv') downloadCsv('satpass-prediction.csv', headers, rows);
      else await downloadServerReport(kind, 'satpass-prediction', headers, rows);
    } catch {
      /* ignore */
    } finally {
      setBusy('');
    }
  };

  if (!passes.length) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-500">
        Click Compute to generate the pass / tracking report.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-gray-950">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <h3 className="text-sm font-semibold">Satellite pass / tracking report</h3>
        <div className="flex gap-1.5">
          {(['csv', 'xlsx', 'pdf'] as const).map((k) => (
            <button
              key={k}
              onClick={() => void doExport(k)}
              disabled={!!busy}
              className="inline-flex items-center gap-1 rounded bg-white/5 px-2 py-1 text-[11px] uppercase tracking-wide text-gray-300 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-50"
            >
              <Download className="h-3 w-3" /> {busy === k ? '…' : k}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-auto">
        <table className="min-w-full text-left text-[11px]">
          <thead className="sticky top-0 bg-gray-900">
            <tr>
              {COLS.map((c) => (
                <th key={c.key} className="whitespace-nowrap px-2 py-2 font-medium text-gray-400">
                  <button onClick={() => onSort(c.key)} className="hover:text-cyan-300">
                    {c.label}
                    {sortKey === c.key ? (asc ? ' ↑' : ' ↓') : ''}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((p) => (
              <tr key={`${p.satelliteName}-${p.startUtc}`} className="border-t border-white/5">
                {COLS.map((c) => (
                  <td key={c.key} className="whitespace-pre-line px-2 py-1.5 align-top text-gray-200">
                    {c.key === 'satelliteName' ? (
                      <span className="inline-flex items-center gap-1.5">
                        <span
                          className="h-2 w-2 rounded-full"
                          style={{ background: p.color }}
                        />
                        {p.satelliteName}
                      </span>
                    ) : (
                      cell(p, c.key, timeZone)
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
