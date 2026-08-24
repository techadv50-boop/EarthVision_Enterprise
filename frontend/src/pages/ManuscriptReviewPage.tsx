import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { citationApi } from '@/services/api';

interface Suggestion {
  id: number;
  score: number;
  reason: string;
  house_citation?: string;
  status: string;
  citation_number?: number | null;
  article?: { title: string; volume?: number; issue_number?: number; page_start: number };
}

interface Paragraph {
  id: number;
  index: number;
  text: string;
  display_text?: string;
  suggestions: Suggestion[];
}

interface Reference {
  number: number;
  house_citation: string;
  title?: string;
}

function byScore(a: Suggestion, b: Suggestion) {
  return (b.score || 0) - (a.score || 0);
}

export default function ManuscriptReviewPage() {
  const { manuscriptId } = useParams();
  const id = Number(manuscriptId);
  const [paras, setParas] = useState<Paragraph[]>([]);
  const [refs, setRefs] = useState<Reference[]>([]);
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [openExtra, setOpenExtra] = useState<Record<number, boolean>>({});
  const [error, setError] = useState('');

  const load = async () => {
    try {
      const { data } = await citationApi.manuscripts.get(id);
      setTitle(data.title || `Manuscript ${id}`);
      setParas(data.paragraphs || []);
      setRefs(data.references || []);
      setError('');
    } catch {
      setError('Could not open this manuscript.');
    }
  };

  useEffect(() => {
    void load();
  }, [id]);

  const decide = async (sugId: number, status: string) => {
    setBusy(true);
    try {
      await citationApi.patchSuggestion(sugId, status);
      await load();
    } catch {
      setMsg('Could not save that decision.');
    } finally {
      setBusy(false);
    }
  };

  const downloadWord = async () => {
    setMsg('Building Word file…');
    try {
      const { data } = await citationApi.manuscripts.export(id);
      const blob = data instanceof Blob ? data : new Blob([data]);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const stem = (title || 'manuscript').replace(/\.[^.]+$/, '');
      a.href = url;
      a.download = `${stem}-cited.docx`;
      a.click();
      URL.revokeObjectURL(url);
      setMsg('Word file downloaded.');
    } catch {
      setMsg('Export failed.');
    }
  };

  const accepted = paras.reduce(
    (n, p) => n + p.suggestions.filter((s) => s.status === 'accepted').length,
    0,
  );
  const pending = paras.reduce(
    (n, p) => n + p.suggestions.filter((s) => s.status === 'pending').length,
    0,
  );

  return (
    <div>
      <p className="text-sm text-gray-500 mb-3">
        <Link to="/manuscripts">Manuscripts</Link> / {title}
      </p>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h2 className="text-2xl font-semibold">{title}</h2>
          <p className="text-sm text-gray-400">
            {pending} waiting · {accepted} accepted · {refs.length} unique references
          </p>
        </div>
        <button className="btn-primary" type="button" disabled={busy} onClick={() => void downloadWord()}>
          Export amended Word file
        </button>
      </div>
      {msg && <p className="text-earth-400 text-sm mb-4">{msg}</p>}
      {error && <p className="text-red-400 text-sm mb-4">{error}</p>}

      <div className="mx-auto max-w-3xl bg-[#f7f3ea] text-gray-900 rounded-sm shadow-[0_20px_60px_rgba(0,0,0,0.45)] px-8 sm:px-12 py-12 min-h-[70vh]">
        <h1 className="text-center font-serif text-2xl mb-10">{title.replace(/\.[^.]+$/, '')}</h1>
        {paras.map((p) => {
          const waiting = [...p.suggestions.filter((s) => s.status === 'pending')].sort(byScore);
          const kept = [...p.suggestions.filter((s) => s.status === 'accepted')].sort(
            (a, b) => (a.citation_number || 0) - (b.citation_number || 0),
          );
          const dropped = p.suggestions.filter((s) => s.status === 'rejected');
          const top = waiting[0];
          const extra = waiting.slice(1);
          const showExtra = Boolean(openExtra[p.id]);
          return (
            <section key={p.id} className="mb-8">
              <p className="font-serif text-[17px] leading-8 whitespace-pre-wrap">
                {p.display_text || p.text}
              </p>
              {top && (
                <SuggestionCard
                  suggestion={top}
                  busy={busy}
                  onDecide={decide}
                  heading="Suggested citation"
                />
              )}
              {extra.length > 0 && (
                <div className="mt-2">
                  <button
                    type="button"
                    className="text-xs text-amber-800 underline"
                    onClick={() => setOpenExtra((m) => ({ ...m, [p.id]: !showExtra }))}
                  >
                    {showExtra ? 'Hide other suggestions' : `Show ${extra.length} other suggestion${extra.length === 1 ? '' : 's'}`}
                  </button>
                  {showExtra &&
                    extra.map((s) => (
                      <SuggestionCard
                        key={s.id}
                        suggestion={s}
                        busy={busy}
                        onDecide={decide}
                        heading="Other house citation"
                      />
                    ))}
                </div>
              )}
              {kept.map((s) => (
                <p key={s.id} className="mt-2 text-xs text-emerald-800">
                  Accepted [{s.citation_number}] {s.house_citation}
                </p>
              ))}
              {dropped.length > 0 && (
                <p className="mt-1 text-xs text-gray-500">
                  {dropped.length} rejected
                  {dropped.slice(0, 3).map((s) => (
                    <button
                      key={s.id}
                      className="underline ml-2"
                      type="button"
                      disabled={busy}
                      onClick={() => void decide(s.id, 'pending')}
                    >
                      undo {s.article?.title ? s.article.title.slice(0, 28) : 'suggestion'}
                    </button>
                  ))}
                </p>
              )}
            </section>
          );
        })}

        {refs.length > 0 && (
          <section className="mt-12 pt-6 border-t border-gray-400">
            <h2 className="font-serif text-xl mb-4">References</h2>
            <ol className="space-y-2">
              {refs.map((r) => (
                <li key={r.number} className="font-serif text-sm leading-6">
                  <span className="font-medium">[{r.number}]</span> {r.house_citation}
                </li>
              ))}
            </ol>
          </section>
        )}
        {paras.length === 0 && !error && (
          <p className="text-gray-500 text-center">No paragraphs were found in this file.</p>
        )}
      </div>
    </div>
  );
}

function SuggestionCard({
  suggestion,
  busy,
  onDecide,
  heading,
}: {
  suggestion: Suggestion;
  busy: boolean;
  onDecide: (id: number, status: string) => void;
  heading: string;
}) {
  return (
    <div className="mt-3 border-l-4 border-amber-400 bg-amber-50 px-3 py-3 text-sm">
      <p className="text-amber-900 font-medium">
        {heading}
        {suggestion.article?.title ? `: ${suggestion.article.title}` : ''}
      </p>
      <p className="text-gray-700 mt-1">{suggestion.reason}</p>
      {suggestion.house_citation && (
        <p className="text-xs text-gray-600 mt-2 font-serif">{suggestion.house_citation}</p>
      )}
      <div className="flex gap-2 mt-3">
        <button
          className="btn-primary text-sm py-1"
          type="button"
          disabled={busy}
          onClick={() => void onDecide(suggestion.id, 'accepted')}
        >
          Accept
        </button>
        <button
          className="btn-secondary text-sm py-1 text-gray-100"
          type="button"
          disabled={busy}
          onClick={() => void onDecide(suggestion.id, 'rejected')}
        >
          Reject
        </button>
      </div>
    </div>
  );
}
