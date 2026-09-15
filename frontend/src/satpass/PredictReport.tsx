import { useMemo, useState } from 'react';
import { Download } from 'lucide-react';
import type { PassRow } from './predict/types';
import { durationLabel, formatDateInZone, formatInZone } from './predict/time';
import {
  downloadCsv,
  downloadPdf,
  downloadServerReport,
  downloadXlsx,
  fileStem,
  passExportRows,
} from './predict/export';

type Col = 'passDateUtc' | 'satelliteName' | 'startLocal' | 'endLocal' | 'duration' | 'swathKm';

const COLS: { key: Col; label: string }[] = [
  { key: 'passDateUtc', label: 'Date' },
  { key: 'satelliteName', label: 'Satellite name' },
  { key: 'startLocal', label: 'Start (entered AOI, local)' },
  { key: 'endLocal', label: 'End (Left AOI, local)' },
  { key: 'duration', label: 'Duration' },
  { key: 'swathKm', label: 'Swath' },
];

function cell(p: PassRow, key: Col, tz: string): string {
  switch (key) {
    case 'passDateUtc':
      return formatDateInZone(p.startUtc, tz);
    case 'duration':
      return durationLabel(p.durationSec);
    case 'startLocal':
      return formatInZone(p.startUtc, tz);
    case 'endLocal':
      return formatInZone(p.endUtc, tz);
    case 'swathKm':
      return p.swathKm == null ? '—' : `${p.swathKm} km`;
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
  const [exportKind, setExportKind] = useState<'csv' | 'xlsx' | 'pdf' | null>(null);
  const [reportTitle, setReportTitle] = useState('');
  const [exportError, setExportError] = useState('');

  const sorted = useMemo(() => {
    const copy = [...passes];
    copy.sort((a, b) => {
      if (sortKey === 'duration' || sortKey === 'swathKm') {
        const an = sortKey === 'duration' ? a.durationSec : Number(a.swathKm ?? 0);
        const bn = sortKey === 'duration' ? b.durationSec : Number(b.swathKm ?? 0);
        return asc ? an - bn : bn - an;
      }
      if (sortKey === 'startLocal' || sortKey === 'endLocal' || sortKey === 'passDateUtc') {
        const av = sortKey === 'endLocal' ? a.endUtc : a.startUtc;
        const bv = sortKey === 'endLocal' ? b.endUtc : b.startUtc;
        return asc ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      const av = cell(a, sortKey, timeZone);
      const bv = cell(b, sortKey, timeZone);
      return asc ? av.localeCompare(bv) : bv.localeCompare(av);
    });
    return copy;
  }, [passes, sortKey, asc, timeZone]);

  const onSort = (key: Col) => {
    if (sortKey === key) setAsc((v) => !v);
    else {
      setSortKey(key);
      setAsc(true);
    }
  };

  const askTitle = (kind: 'csv' | 'xlsx' | 'pdf') => {
    setExportError('');
    setReportTitle((cur) => cur.trim() || passes[0]?.targetName || 'SatPass AOI report');
    setExportKind(kind);
  };

  const doExport = async () => {
    const kind = exportKind;
    const title = reportTitle.trim();
    if (!kind) return;
    if (!title) {
      setExportError('Enter a report title before export.');
      return;
    }
    const { headers, rows } = passExportRows(sorted, timeZone);
    const stem = fileStem(title);
    setBusy(kind);
    setExportError('');
    try {
      if (kind === 'csv') downloadCsv(`${stem}.csv`, title, headers, rows);
      else if (kind === 'xlsx') {
        try {
          await downloadServerReport('xlsx', title, headers, rows);
        } catch {
          await downloadXlsx(`${stem}.xlsx`, headers, rows);
        }
      } else {
        try {
          await downloadServerReport('pdf', title, headers, rows);
        } catch {
          downloadPdf(`${stem}.pdf`, title, headers, rows);
        }
      }
      setExportKind(null);
    } catch {
      setExportError('Export failed. Try again.');
    } finally {
      setBusy('');
    }
  };

  if (!passes.length) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-500">
        Click Compute to generate valid imaging passes (optical: daylight only; SAR: day and night).
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-gray-950">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <h3 className="text-sm font-semibold">Satellite pass / tracking report</h3>
        <div className="flex gap-1.5">
          <button
            onClick={() => askTitle('xlsx')}
            disabled={!!busy}
            className="inline-flex items-center gap-1 rounded bg-cyan-600 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-white hover:bg-cyan-500 disabled:opacity-50"
          >
            <Download className="h-3 w-3" /> {busy === 'xlsx' ? '…' : 'Excel'}
          </button>
          {(['csv', 'pdf'] as const).map((k) => (
            <button
              key={k}
              onClick={() => askTitle(k)}
              disabled={!!busy}
              className="inline-flex items-center gap-1 rounded bg-white/5 px-2 py-1 text-[11px] uppercase tracking-wide text-gray-300 ring-1 ring-white/10 hover:bg-white/10 disabled:opacity-50"
            >
              <Download className="h-3 w-3" /> {busy === k ? '…' : k}
            </button>
          ))}
        </div>
      </div>
      {exportKind ? (
        <div className="border-b border-white/10 bg-gray-900 px-3 py-2">
          <p className="mb-1 text-[11px] font-medium text-gray-200">
            Enter a title for the {exportKind.toUpperCase()} report
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <input
              autoFocus
              value={reportTitle}
              onChange={(e) => setReportTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void doExport();
                if (e.key === 'Escape') setExportKind(null);
              }}
              placeholder="Report title"
              className="min-w-[220px] flex-1 rounded bg-gray-950 px-2 py-1.5 text-sm text-gray-100 outline-none ring-1 ring-cyan-500/50"
            />
            <button
              onClick={() => void doExport()}
              disabled={!!busy}
              className="rounded bg-cyan-600 px-2.5 py-1 text-[11px] font-semibold uppercase text-white hover:bg-cyan-500 disabled:opacity-50"
            >
              {busy ? '…' : `Export ${exportKind}`}
            </button>
            <button
              onClick={() => setExportKind(null)}
              className="rounded px-2 py-1 text-[11px] text-gray-400 hover:text-gray-200"
            >
              Cancel
            </button>
          </div>
          {exportError ? <p className="mt-1 text-[11px] text-red-400">{exportError}</p> : null}
        </div>
      ) : null}
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
              <tr key={p.passId} className="border-t border-white/5">
                {COLS.map((c) => (
                  <td key={c.key} className="whitespace-pre-line px-2 py-1.5 align-top text-gray-200">
                    {c.key === 'satelliteName' ? (
                      <span className="inline-flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
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
