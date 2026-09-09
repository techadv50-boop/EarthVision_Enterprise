import { useState } from 'react';
import { citationApi } from '@/services/api';

interface RefItem {
  number?: number | null;
  text: string;
  body: string;
  doi?: string | null;
}

interface DiffRow {
  original?: RefItem | null;
  returned?: RefItem | null;
  detail: string;
  similarity?: number;
}

interface IntegrityResult {
  status: 'pass' | 'fail';
  summary: string;
  order_changed: boolean;
  original_count: number;
  returned_count: number;
  unchanged_count: number;
  removed: DiffRow[];
  added: DiffRow[];
  changed: DiffRow[];
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
  return (
    <p className={`text-sm leading-relaxed ${color}`}>
      {item.text}
    </p>
  );
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

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">Reference check</h2>
      <p className="text-gray-400 mb-5 max-w-3xl">
        Upload the Word file you sent to staff, then the file they returned. The check reads only
        the References section. A shuffled list is acceptable when each reference keeps the same
        number and the same work. Removed, added, rewritten, or renumbered items are flagged.
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
          <div
            className={`panel p-4 ${
              result.status === 'pass' ? 'border-emerald-700' : 'border-red-700'
            }`}
          >
            <p className={`text-sm font-semibold ${result.status === 'pass' ? 'text-emerald-400' : 'text-red-400'}`}>
              {result.status === 'pass' ? 'References intact' : 'References do not match'}
            </p>
            <p className="text-gray-300 mt-1">{result.summary}</p>
            {result.order_changed && (
              <p className="text-amber-300 text-sm mt-2">
                List order differs, but each number still points to the same reference.
              </p>
            )}
            <p className="text-xs text-gray-500 mt-2">
              Original {result.original_count} · Returned {result.returned_count} · Unchanged{' '}
              {result.unchanged_count}
            </p>
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
            title="Added"
            rows={result.added}
            empty="No extra reference was introduced."
            tone="warn"
          />
          <DiffSection
            title="Changed"
            rows={result.changed}
            empty="No numbered reference was rewritten."
            tone="bad"
          />
          <DiffSection
            title="Renumbered"
            rows={result.renumbered}
            empty="Every surviving reference kept its original number."
            tone="warn"
          />
          <div className="grid md:grid-cols-2 gap-4">
            <section className="panel p-4">
              <h3 className="font-medium mb-3">Original list</h3>
              <div className="space-y-2 max-h-[28rem] overflow-auto pr-1">
                {result.original.items.map((item, i) => (
                  <RefLine key={`o-${i}`} item={item} />
                ))}
              </div>
            </section>
            <section className="panel p-4">
              <h3 className="font-medium mb-3">Returned list</h3>
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
