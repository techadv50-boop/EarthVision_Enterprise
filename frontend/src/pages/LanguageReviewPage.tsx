import { useMemo, useState, type ReactNode } from 'react';
import { citationApi } from '@/services/api';

type Category =
  | 'english'
  | 'sentence_structure'
  | 'broken_sentence'
  | 'slang'
  | 'ambiguity'
  | 'irrelevant_word'
  | string;

interface Issue {
  id: number;
  paragraph_index: number;
  quote: string;
  category: Category;
  severity: 'high' | 'medium' | 'low' | string;
  suggestion: string;
  explanation: string;
  source?: string;
}

interface Paragraph {
  index: number;
  text: string;
  issue_ids: number[];
}

interface LanguageResult {
  filename: string;
  engine: string;
  engine_note: string;
  summary: {
    paragraph_count: number;
    issue_count: number;
    by_category: Record<string, number>;
    by_severity: Record<string, number>;
  };
  paragraphs: Paragraph[];
  issues: Issue[];
}

const CATEGORY_LABEL: Record<string, string> = {
  english: 'English',
  sentence_structure: 'Sentence structure',
  broken_sentence: 'Broken sentence',
  slang: 'Slang / informal',
  ambiguity: 'Ambiguity',
  irrelevant_word: 'Irrelevant / filler',
};

function categoryLabel(value: string) {
  return CATEGORY_LABEL[value] || value.replace(/_/g, ' ');
}

function locateQuote(text: string, quote: string): { start: number; end: number } | null {
  if (!quote) return null;
  const direct = text.indexOf(quote);
  if (direct >= 0) return { start: direct, end: direct + quote.length };
  const lower = text.toLowerCase();
  const found = lower.indexOf(quote.toLowerCase());
  if (found >= 0) return { start: found, end: found + quote.length };
  return null;
}

function ParagraphView({
  paragraph,
  issues,
  activeId,
  onSelect,
}: {
  paragraph: Paragraph;
  issues: Issue[];
  activeId: number | null;
  onSelect: (id: number) => void;
}) {
  const marks = issues
    .map((issue) => {
      const span = locateQuote(paragraph.text, issue.quote);
      if (!span) return null;
      return { ...span, issue };
    })
    .filter((row): row is { start: number; end: number; issue: Issue } => Boolean(row))
    .sort((a, b) => a.start - b.start || a.end - b.end);

  const kept: typeof marks = [];
  let cursor = 0;
  for (const mark of marks) {
    if (mark.start < cursor) continue;
    kept.push(mark);
    cursor = mark.end;
  }

  const nodes: ReactNode[] = [];
  let pos = 0;
  kept.forEach((mark, i) => {
    if (mark.start > pos) {
      nodes.push(<span key={`t-${paragraph.index}-${i}`}>{paragraph.text.slice(pos, mark.start)}</span>);
    }
    const sev = mark.issue.severity === 'high' ? 'high' : mark.issue.severity === 'low' ? 'low' : 'medium';
    const active = activeId === mark.issue.id;
    nodes.push(
      <mark
        key={`m-${mark.issue.id}`}
        id={`issue-${mark.issue.id}`}
        className={`review-mark review-mark-${sev} ${active ? 'review-mark-active' : ''}`}
        title={mark.issue.explanation}
        onClick={() => onSelect(mark.issue.id)}
      >
        {paragraph.text.slice(mark.start, mark.end)}
      </mark>
    );
    pos = mark.end;
  });
  if (pos < paragraph.text.length) {
    nodes.push(<span key={`t-end-${paragraph.index}`}>{paragraph.text.slice(pos)}</span>);
  }
  if (kept.length === 0 && issues.length > 0) {
    return (
      <p
        className={`whitespace-pre-wrap leading-relaxed ${
          activeId && issues.some((i) => i.id === activeId) ? 'review-mark-active rounded-md p-1' : ''
        }`}
      >
        {paragraph.text}
      </p>
    );
  }
  return <p className="whitespace-pre-wrap leading-relaxed">{nodes}</p>;
}

export default function LanguageReviewPage() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<LanguageResult | null>(null);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [filter, setFilter] = useState<string>('all');

  const filteredIssues = useMemo(() => {
    if (!result) return [];
    if (filter === 'all') return result.issues;
    return result.issues.filter((issue) => issue.category === filter);
  }, [result, filter]);

  const issuesByPara = useMemo(() => {
    const map = new Map<number, Issue[]>();
    for (const issue of filteredIssues) {
      const list = map.get(issue.paragraph_index) || [];
      list.push(issue);
      map.set(issue.paragraph_index, list);
    }
    return map;
  }, [filteredIssues]);

  const selectIssue = (id: number) => {
    setActiveId(id);
    const node = document.getElementById(`issue-${id}`) || document.getElementById(`para-card-${id}`);
    node?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  const upload = async (file: File) => {
    setBusy(true);
    setError('');
    setActiveId(null);
    try {
      const { data } = await citationApi.review.language(file);
      setResult(data as LanguageResult);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Could not read that file. Upload a Word, PDF, or text manuscript.';
      setError(String(detail));
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">English review</h2>
      <p className="text-gray-400 mb-5 max-w-3xl">
        Upload the manuscript that will be published. The reviewer flags English usage, sentence
        structure, broken sentences, slang, ambiguity, and irrelevant wording. The full document
        appears below with corrections marked in place — click a mark or a suggestion card to jump
        between them.
      </p>
      <form className="panel p-4 max-w-xl space-y-3" onSubmit={(e) => e.preventDefault()}>
        <label className="block text-sm text-gray-300" htmlFor="language-upload">
          Manuscript file
        </label>
        <input
          id="language-upload"
          type="file"
          disabled={busy}
          accept=".docx,.pdf,.txt,.md,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/pdf,text/plain"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.currentTarget.value = '';
            if (file) void upload(file);
          }}
        />
        <p className="text-xs text-gray-500">
          Word (.docx) is preferred. PDF and plain text are also accepted. GPT is used when the
          server has an API key; otherwise the built-in checker still runs.
        </p>
      </form>
      {busy && <p className="text-earth-400 text-sm mt-3">Reviewing the document…</p>}
      {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

      {result && (
        <div className="mt-6 space-y-4">
          <div className="panel p-4 flex flex-wrap gap-4 items-start justify-between">
            <div>
              <p className="font-medium">{result.filename}</p>
              <p className="text-sm text-gray-400 mt-1">{result.engine_note}</p>
              <p className="text-xs text-gray-500 mt-2">
                {result.summary.paragraph_count} paragraphs · {result.summary.issue_count} suggestions
              </p>
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              {Object.entries(result.summary.by_severity).map(([key, count]) => (
                <span key={key} className="px-2 py-1 rounded bg-gray-800 text-gray-300">
                  {key}: {count}
                </span>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className={`px-3 py-1 rounded text-sm ${filter === 'all' ? 'bg-earth-600 text-white' : 'bg-gray-800 text-gray-300'}`}
              onClick={() => setFilter('all')}
            >
              All ({result.issues.length})
            </button>
            {Object.entries(result.summary.by_category)
              .filter(([, count]) => count > 0)
              .map(([key, count]) => (
                <button
                  key={key}
                  type="button"
                  className={`px-3 py-1 rounded text-sm ${
                    filter === key ? 'bg-earth-600 text-white' : 'bg-gray-800 text-gray-300'
                  }`}
                  onClick={() => setFilter(key)}
                >
                  {categoryLabel(key)} ({count})
                </button>
              ))}
          </div>
          <div className="grid lg:grid-cols-[minmax(0,1.4fr)_minmax(20rem,0.9fr)] gap-4 items-start">
            <div className="panel p-5 max-h-[70vh] overflow-auto space-y-5">
              <h3 className="text-sm uppercase tracking-wide text-gray-500">Document to publish</h3>
              {result.paragraphs.map((para) => {
                const issues = issuesByPara.get(para.index) || [];
                const flagged = issues.length > 0;
                return (
                  <div
                    key={para.index}
                    id={`para-${para.index}`}
                    className={`rounded-md ${flagged ? 'bg-gray-800/40 p-3' : ''}`}
                  >
                    <ParagraphView
                      paragraph={para}
                      issues={issues}
                      activeId={activeId}
                      onSelect={selectIssue}
                    />
                  </div>
                );
              })}
            </div>
            <div className="panel p-4 max-h-[70vh] overflow-auto space-y-3">
              <h3 className="text-sm uppercase tracking-wide text-gray-500">
                Corrections / suggestions
              </h3>
              {filteredIssues.length === 0 ? (
                <p className="text-sm text-emerald-400">No issues in this view.</p>
              ) : (
                filteredIssues.map((issue) => (
                  <button
                    key={issue.id}
                    id={`para-card-${issue.id}`}
                    type="button"
                    onClick={() => {
                      setActiveId(issue.id);
                      document.getElementById(`issue-${issue.id}`)?.scrollIntoView({
                        behavior: 'smooth',
                        block: 'center',
                      });
                      document.getElementById(`para-${issue.paragraph_index}`)?.scrollIntoView({
                        behavior: 'smooth',
                        block: 'center',
                      });
                    }}
                    className={`w-full text-left rounded-lg border p-3 ${
                      activeId === issue.id
                        ? 'border-earth-500 bg-gray-800'
                        : 'border-gray-800 bg-gray-900/40 hover:border-gray-600'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span className="text-xs text-earth-400">{categoryLabel(issue.category)}</span>
                      <span
                        className={`text-[11px] uppercase ${
                          issue.severity === 'high'
                            ? 'text-red-400'
                            : issue.severity === 'low'
                              ? 'text-sky-400'
                              : 'text-amber-400'
                        }`}
                      >
                        {issue.severity}
                      </span>
                    </div>
                    <p className="text-sm text-red-200 line-through decoration-red-400/80">
                      {issue.quote}
                    </p>
                    {issue.suggestion && (
                      <p className="text-sm text-emerald-300 mt-1">{issue.suggestion}</p>
                    )}
                    <p className="text-xs text-gray-400 mt-2">{issue.explanation}</p>
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
