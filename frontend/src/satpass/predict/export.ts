import type { PassRow } from './types';
import { durationLabel, formatInZone, formatUtc } from './time';

export function passExportRows(passes: PassRow[], timeZone: string): { headers: string[]; rows: string[][] } {
  const headers = [
    'Pass ID',
    'Satellite',
    'Type',
    'Date',
    'Start Tracking (local)',
    'Start Tracking (UTC)',
    'End Tracking (local)',
    'End Tracking (UTC)',
    'Duration',
    'Max elevation (deg)',
    'Max elevation time (UTC)',
    'AOS',
    'LOS',
    'Day/Night',
    'Imaging eligibility',
  ];
  const rows = passes.map((p) => [
    p.passId,
    p.satelliteName,
    p.satelliteKind === 'sar' ? 'SAR' : 'Optical',
    p.passDateUtc,
    formatInZone(p.startUtc, timeZone),
    formatUtc(p.startUtc),
    formatInZone(p.endUtc, timeZone),
    formatUtc(p.endUtc),
    durationLabel(p.durationSec),
    p.maxElevationDeg == null ? '' : String(p.maxElevationDeg),
    p.maxElevationUtc ? formatUtc(p.maxElevationUtc) : '',
    formatUtc(p.aosUtc),
    formatUtc(p.losUtc),
    p.visibility,
    p.imagingStatus,
  ]);
  return { headers, rows };
}

export function downloadCsv(filename: string, headers: string[], rows: string[][]) {
  const esc = (c: string) => `"${c.replace(/"/g, '""')}"`;
  const text = [headers, ...rows].map((r) => r.map(esc).join(',')).join('\n');
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

export async function downloadServerReport(
  format: 'xlsx' | 'pdf',
  title: string,
  headers: string[],
  rows: string[][],
) {
  const token = localStorage.getItem('access_token');
  const resp = await fetch('/api/v1/satellites/predict/export', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ format, title, headers, rows }),
  });
  if (!resp.ok) throw new Error('Export failed');
  const blob = await resp.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = format === 'pdf' ? `${title}.pdf` : `${title}.xlsx`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export async function uploadGeometryFiles(files: File[]): Promise<GeoJSON.FeatureCollection> {
  const token = localStorage.getItem('access_token');
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  const resp = await fetch('/api/v1/satellites/predict/geometry', {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: fd,
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(detail || 'Could not parse the uploaded file.');
  }
  const data = (await resp.json()) as { geojson: GeoJSON.FeatureCollection };
  return data.geojson;
}
