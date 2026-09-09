import { useState } from 'react';
import { citationApi } from '@/services/api';

interface RefItem {
  number?: number | null;
  text: string;
  body: string;
  doi?: string | null;
  index?: number;
}

interface DiffRow {
  original?: RefItem | null;
  returned?: RefItem | null;
  detail: string;
  similarity?: number;
}

interface IntegrityResult {
  status: 'pass' | 'warn' | 'fail';
  summary: string;
  overall?: {
    original: number;
    returned: number;
    unchanged: number;
    removed: number;
    added: number;
    amended: number;
    style_changed: number;
    place_changed: number;
    verdict: string;
    lines: string[];
  };
  order_changed: boolean;
  original_count: number;
  returned_count: number;
  unchanged_count: number;
  removed: DiffRow[];
  added: DiffRow[];
  changed: DiffRow[];
  amended?: DiffRow[];
  style_changed?: DiffRow[];
  place_changed?: DiffRow[];
  renumbered: DiffRow[];
  warnings: string[];
  original: { filename: string; heading?: string | null; count: number; items: RefItem[] };
  returned: { filename: string; heading?: string | null; count: number; items: RefItem[] };
}

function FilePick({
  id,
  label,
  hint,
  file,
  onFile,
  disabled,
}: {
  id: string;
  label: string;
  hint: string;
  file: File | null;
  onFile: (file: File | null) => void;
  disabled?: boolean;
}) {
  return (
    <label className="panel p-4 block cursor-pointer hover:border-earth-700" htmlFor={id}>
      <span className="block text-sm text-gray-200 mb-1">{label}</span>
      <span className="block text-xs text-gray-500 mb-3">{hint}</span>
      <input
        id={id}
        type="file"
        disabled={disabled}
        accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        className="block w-full text-sm text-gray-300"
        onChange={(e) => {
          const next = e.target.files?.[0] || null;
          onFile(next);
        }}
      />
      {file && <p className="text-xs text-earth-400 mt-2 truncate">{file.name}</p>}
    </label>
  );
}

function RefLine({ item, tone }: { item?: RefItem | null; tone?: 'bad' | 'good' | 'warn' }) {
  if (!item) return <p className="text-gray-600 text-sm">—</p>;
  const color =
    tone === 'bad' ? 'text-red-300' : tone === 'warn' ? 'text-amber-200' : 'text-gray-200';
  return <p className={`text-sm leading-relaxed ${color}`}>{item.text}</p>;
}

function DiffSection({
  title,
  rows,
  empty,
  tone,
}: {
  title: string;
  rows: DiffRow[];
  empty: string;
  tone: 'bad' | 'warn';
}) {
  return (
    <section className="panel p-4">
      <h3 className="font-medium mb-3">
        {title} <span className="text-gray-500">({rows.length})</span>
      </h3>
      {rows.length === 0 ? (
        <p className="text-sm text-gray-500">{empty}</p>
      ) : (
        <div className="space-y-4">
          {rows.map((row, i) => (
            <div key={`${title}-${i}`} className="border-t border-gray-800 pt-3 first:border-0 first:pt-0">
              <p className="text-xs text-gray-400 mb-2">{row.detail}</p>
              <div className="grid md:grid-cols-2 gap-3">
                <div>
                  <p className="text-[11px] uppercase tracking-wide text-gray-500 mb-1">Original</p>
                  <RefLine item={row.original} tone={tone} />
                </div>
                <div>
                  <p className="text-[11px] uppercase tracking-wide text-gray-500 mb-1">Returned</p>
                  <RefLine item={row.returned} tone={tone} />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default function ReferenceCheckPage() {
  const [original, setOriginal] = useState<File | null>(null);
  const [returned, setReturned] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<IntegrityResult | null>(null);

  const run = async () => {
    if (!original || !returned) {
      setError('Upload both Word files first.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const { data } = await citationApi.review.referenceIntegrity(original, returned);
      setResult(data as IntegrityResult);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Could not compare those files. Use .docx manuscripts.';
      setError(String(detail));
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  const overall = result?.overall;
  const amended = result?.amended || result?.changed || [];
  const styleChanged = result?.style_changed || [];
  const placeChanged = result?.place_changed || result?.renumbered || [];
  const statusColor =
    result?.status === 'pass'
      ? 'border-emerald-700 text-emerald-400'
      : result?.status === 'warn'
        ? 'border-amber-700 text-amber-300'
        : 'border-red-700 text-red-400';

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">Reference check</h2>
      <p className="text-gray-400 mb-5 max-w-3xl">
        Upload the Word file you sent to staff, then the file they returned. The check splits the
        References section into individual works and reports what was removed, newly added,
        amended, style-only changed, or moved in place. A shuffled list is reported as a place
        change; it is not treated as a deletion.
      </p>
      <div className="grid md:grid-cols-2 gap-4 max-w-4xl">
        <FilePick
          id="original-docx"
          label="1. File you gave to staff"
          hint="Original .docx"
          file={original}
          onFile={setOriginal}
          disabled={busy}
        />
        <FilePick
          id="returned-docx"
          label="2. File they returned"
          hint="Returned .docx"
          file={returned}
          onFile={setReturned}
          disabled={busy}
        />
      </div>
      <button
        type="button"
        className="btn-primary mt-4"
        disabled={busy || !original || !returned}
        onClick={() => void run()}
      >
        {busy ? 'Comparing references…' : 'Run integrity check'}
      </button>
      {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

      {result && (
        <div className="mt-8 space-y-4">
          <div className={`panel p-4 ${statusColor.split(' ').slice(0, 1).join(' ')}`}>
            <p className={`text-sm font-semibold ${statusColor.split(' ').slice(1).join(' ')}`}>
              Overall report
            </p>
            <p className="text-gray-200 mt-2">{overall?.verdict || result.summary}</p>
            {overall?.lines && (
              <ul className="mt-3 text-sm text-gray-300 space-y-1 list-disc pl-5">
                {overall.lines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
            {overall && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-4 text-xs">
                <span className="bg-gray-800 rounded px-2 py-1">Removed {overall.removed}</span>
                <span className="bg-gray-800 rounded px-2 py-1">Added {overall.added}</span>
                <span className="bg-gray-800 rounded px-2 py-1">Amended {overall.amended}</span>
                <span className="bg-gray-800 rounded px-2 py-1">Style {overall.style_changed}</span>
                <span className="bg-gray-800 rounded px-2 py-1">Place {overall.place_changed}</span>
                <span className="bg-gray-800 rounded px-2 py-1">Unchanged {overall.unchanged}</span>
                <span className="bg-gray-800 rounded px-2 py-1">Original {overall.original}</span>
                <span className="bg-gray-800 rounded px-2 py-1">Returned {overall.returned}</span>
              </div>
            )}
          </div>
          {result.warnings.length > 0 && (
            <div className="panel p-4 border-amber-800">
              {result.warnings.map((w) => (
                <p key={w} className="text-sm text-amber-300">
                  {w}
                </p>
              ))}
            </div>
          )}
          <DiffSection
            title="Removed"
            rows={result.removed}
            empty="No original reference is missing."
            tone="bad"
          />
          <DiffSection
            title="Newly added"
            rows={result.added}
            empty="No extra reference was introduced."
            tone="warn"
          />
          <DiffSection
            title="Amended (content)"
            rows={amended}
            empty="No reference was rewritten."
            tone="bad"
          />
          <DiffSection
            title="Style only"
            rows={styleChanged}
            empty="No punctuation / italic / spacing-only edits."
            tone="warn"
          />
          <DiffSection
            title="Place / order / number"
            rows={placeChanged}
            empty="Every surviving reference stayed in the same place with the same number."
            tone="warn"
          />
          <div className="grid md:grid-cols-2 gap-4">
            <section className="panel p-4">
              <h3 className="font-medium mb-3">Original list ({result.original.count})</h3>
              <div className="space-y-2 max-h-[28rem] overflow-auto pr-1">
                {result.original.items.map((item, i) => (
                  <RefLine key={`o-${i}`} item={item} />
                ))}
              </div>
            </section>
            <section className="panel p-4">
              <h3 className="font-medium mb-3">Returned list ({result.returned.count})</h3>
              <div className="space-y-2 max-h-[28rem] overflow-auto pr-1">
                {result.returned.items.map((item, i) => (
                  <RefLine key={`r-${i}`} item={item} />
                ))}
              </div>
            </section>
          </div>
        </div>
      )}
    </div>
  );
}
