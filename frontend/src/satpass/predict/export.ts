import type { PassRow } from './types';
import { durationLabel, formatDateInZone, formatInZone } from './time';

export function passExportRows(passes: PassRow[], timeZone: string): { headers: string[]; rows: string[][] } {
  const headers = [
    'Date',
    'Satellite name',
    'Start (entered AOI, local)',
    'End (Left AOI, local)',
    'Duration',
    'Swath',
  ];
  const rows = passes.map((p) => [
    formatDateInZone(p.startUtc, timeZone),
    p.satelliteName,
    formatInZone(p.startUtc, timeZone),
    formatInZone(p.endUtc, timeZone),
    durationLabel(p.durationSec),
    p.swathKm == null ? '' : `${p.swathKm} km`,
  ]);
  return { headers, rows };
}

function xmlEscape(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
}

function sheetXml(headers: string[], rows: string[][]): string {
  const cell = (ref: string, value: string) =>
    `<c r="${ref}" t="inlineStr"><is><t>${xmlEscape(value)}</t></is></c>`;
  const colLetter = (i: number) => {
    let n = i;
    let s = '';
    while (n >= 0) {
      s = String.fromCharCode((n % 26) + 65) + s;
      n = Math.floor(n / 26) - 1;
    }
    return s;
  };
  const lines = [
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>',
    `<row r="1">${headers.map((h, i) => cell(`${colLetter(i)}1`, h)).join('')}</row>`,
  ];
  rows.forEach((row, ri) => {
    const r = ri + 2;
    lines.push(`<row r="${r}">${row.map((v, i) => cell(`${colLetter(i)}${r}`, v)).join('')}</row>`);
  });
  lines.push('</sheetData></worksheet>');
  return lines.join('');
}

async function zipStore(files: { name: string; data: Uint8Array }[]): Promise<Blob> {
  const crcTable = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n += 1) {
      let c = n;
      for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c;
    }
    return t;
  })();
  const crc32 = (buf: Uint8Array) => {
    let c = 0xffffffff;
    for (let i = 0; i < buf.length; i += 1) c = crcTable[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const u16 = (n: number) => {
    const b = new Uint8Array(2);
    new DataView(b.buffer).setUint16(0, n, true);
    return b;
  };
  const u32 = (n: number) => {
    const b = new Uint8Array(4);
    new DataView(b.buffer).setUint32(0, n, true);
    return b;
  };
  const parts: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;
  const encoder = new TextEncoder();
  for (const f of files) {
    const name = encoder.encode(f.name);
    const crc = crc32(f.data);
    const local = [
      u32(0x04034b50),
      u16(20),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(crc),
      u32(f.data.length),
      u32(f.data.length),
      u16(name.length),
      u16(0),
      name,
      f.data,
    ];
    const localBuf = concat(local);
    parts.push(localBuf);
    central.push(
      concat([
        u32(0x02014b50),
        u16(20),
        u16(20),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(crc),
        u32(f.data.length),
        u32(f.data.length),
        u16(name.length),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(0),
        u32(offset),
        name,
      ]),
    );
    offset += localBuf.length;
  }
  const centralBuf = concat(central);
  const end = concat([u32(0x06054b50), u16(0), u16(0), u16(files.length), u16(files.length), u32(centralBuf.length), u32(offset), u16(0)]);
  return new Blob([concat([...parts, centralBuf, end])], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
}

function concat(chunks: Uint8Array[]): Uint8Array {
  const n = chunks.reduce((s, c) => s + c.length, 0);
  const out = new Uint8Array(n);
  let o = 0;
  for (const c of chunks) {
    out.set(c, o);
    o += c.length;
  }
  return out;
}

/** Browser-side .xlsx so Excel export works even if the API is unreachable. */
export async function downloadXlsx(filename: string, headers: string[], rows: string[][]) {
  const enc = new TextEncoder();
  const sheet = sheetXml(headers, rows);
  const blob = await zipStore([
    {
      name: '[Content_Types].xml',
      data: enc.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
          '<Default Extension="xml" ContentType="application/xml"/>' +
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
          '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' +
          '</Types>',
      ),
    },
    {
      name: '_rels/.rels',
      data: enc.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
          '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
          '</Relationships>',
      ),
    },
    {
      name: 'xl/workbook.xml',
      data: enc.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
          '<sheets><sheet name="AOI passes" sheetId="1" r:id="rId1"/></sheets></workbook>',
      ),
    },
    {
      name: 'xl/_rels/workbook.xml.rels',
      data: enc.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
          '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' +
          '</Relationships>',
      ),
    },
    { name: 'xl/worksheets/sheet1.xml', data: enc.encode(sheet) },
  ]);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`;
  a.click();
  URL.revokeObjectURL(a.href);
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
