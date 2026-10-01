import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { KeyRound, Sparkles } from 'lucide-react';
import { citationApi } from '@/services/api';

interface Issue {
  id: number;
  paragraph_index: number;
  quote: string;
  category: string;
  severity: 'high' | 'medium' | 'low' | string;
  suggestion: string;
  explanation: string;
  rewrite?: string;
  source?: string;
}

interface Paragraph {
  index: number;
  text: string;
  issue_ids: number[];
}

interface ToolDef {
  id: string;
  group: string;
  label: string;
  description: string;
}

interface ToolGroup {
  id: string;
  label: string;
}

interface GptStatus {
  available: boolean;
  enabled?: boolean;
  configured?: boolean;
  source?: string;
  provider: string;
  model?: string | null;
  key_hint?: string;
  can_configure?: boolean;
  note: string;
}

interface LanguageResult {
  filename: string;
  engine: string;
  engine_note: string;
  gpt?: GptStatus;
  tools?: ToolDef[];
  groups?: ToolGroup[];
  summary: {
    paragraph_count: number;
    issue_count: number;
    by_category: Record<string, number>;
    by_severity: Record<string, number>;
    score?: number;
    band?: string;
    verdict?: string;
  };
  paragraphs: Paragraph[];
  issues: Issue[];
}

const FALLBACK_LABEL: Record<string, string> = {
  grammar: 'Grammar',
  agreement: 'Subject–verb agreement',
  spelling: 'Spelling',
  punctuation: 'Punctuation',
  sentence_structure: 'Sentence structure',
  broken_sentence: 'Broken sentence',
  run_on: 'Run-on / comma splice',
  dangling_modifier: 'Dangling modifier',
  parallelism: 'Parallelism',
  slang: 'Slang / informal',
  formality: 'Formality',
  second_person: 'Second person',
  abusive: 'Abusive language',
  bias_language: 'Inclusive language',
  cliche: 'Cliché',
  conciseness: 'Conciseness',
  hedging: 'Hedging',
  redundancy: 'Redundancy',
  irrelevant_word: 'Filler',
  passive_voice: 'Passive voice',
  overclaiming: 'Overclaiming',
  weasel: 'Weasel words',
  opinion: 'Personal opinion',
  ambiguity: 'Ambiguity',
  clarity: 'Clarity',
  word_choice: 'Word choice',
  confused_words: 'Confused words',
  repetition: 'Repetition',
  capitalization: 'Capitalization',
  anthropomorphism: 'Anthropomorphism',
  latin_abbrev: 'Latin abbreviations',
  hyphenation: 'Hyphenation',
  exclamation: 'Exclamation',
  english: 'Grammar',
};

function categoryLabel(value: string, tools: ToolDef[]) {
  return tools.find((tool) => tool.id === value)?.label || FALLBACK_LABEL[value] || value.replace(/_/g, ' ');
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
  const [tools, setTools] = useState<ToolDef[]>([]);
  const [groups, setGroups] = useState<ToolGroup[]>([]);
  const [gpt, setGpt] = useState<GptStatus | null>(null);
  const [showKeyForm, setShowKeyForm] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const [gptModel, setGptModel] = useState('gpt-4o-mini');
  const [gptBusy, setGptBusy] = useState(false);
  const [gptError, setGptError] = useState('');
  const [gptMessage, setGptMessage] = useState('');

  useEffect(() => {
    let cancelled = false;
    citationApi.review
      .languageTools()
      .then(({ data }) => {
        if (cancelled) return;
        const payload = data as {
          tools?: ToolDef[];
          groups?: ToolGroup[];
          gpt?: GptStatus;
        };
        setTools(payload.tools || []);
        setGroups(payload.groups || []);
        setGpt(payload.gpt || null);
        if (payload.gpt?.model) setGptModel(payload.gpt.model);
      })
      .catch(() => {
        if (!cancelled) setGpt(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const catalogTools = result?.tools?.length ? result.tools : tools;
  const catalogGroups = result?.groups?.length ? result.groups : groups;
  const gptStatus = gpt;
  const counts = result?.summary.by_category || {};

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
    setFilter('all');
    try {
      const { data } = await citationApi.review.language(file);
      const payload = data as LanguageResult;
      setResult(payload);
      if (payload.tools?.length) setTools(payload.tools);
      if (payload.groups?.length) setGroups(payload.groups);
      if (payload.gpt) {
        setGpt(payload.gpt);
        if (payload.gpt.model) setGptModel(payload.gpt.model);
      }
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

  const applyCatalog = (payload: { tools?: ToolDef[]; groups?: ToolGroup[]; gpt?: GptStatus }) => {
    if (payload.tools?.length) setTools(payload.tools);
    if (payload.groups?.length) setGroups(payload.groups);
    if (payload.gpt) {
      setGpt(payload.gpt);
      if (payload.gpt.model) setGptModel(payload.gpt.model);
    }
  };

  const saveGpt = async (enabled: boolean, withKey = false) => {
    setGptBusy(true);
    setGptError('');
    setGptMessage('');
    try {
      const body: { enabled: boolean; api_key?: string; model?: string } = {
        enabled,
        model: gptModel.trim() || 'gpt-4o-mini',
      };
      if (withKey) body.api_key = apiKey.trim();
      const { data } = await citationApi.review.languageGpt(body);
      applyCatalog(data as { tools?: ToolDef[]; groups?: ToolGroup[]; gpt?: GptStatus });
      const next = (data as { gpt?: GptStatus }).gpt;
      if (enabled && next?.available) {
        setGptMessage('GPT is on. Upload a manuscript to use it with the tools below.');
        setShowKeyForm(false);
        setApiKey('');
      } else if (!enabled) {
        setGptMessage('GPT is off. The built-in checker still runs.');
        setShowKeyForm(false);
      }
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Could not save the API key.';
      setGptError(String(detail));
    } finally {
      setGptBusy(false);
    }
  };

  const groupedTools = (catalogGroups.length ? catalogGroups : [{ id: 'all', label: 'Tools' }]).map((group) => ({
    ...group,
    tools: catalogTools.filter((tool) => tool.group === group.id || (!tool.group && group.id === 'all')),
  }));

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">English review</h2>
      <p className="text-gray-400 mb-5 max-w-3xl">
        Upload the manuscript that will be published. Each tool below runs on the full
        document: grammar, sentence structure, broken sentences, run-ons, slang, formality,
        conciseness, ambiguity, word choice, repetition, passive voice, abusive language,
        and related academic-English checks. Turn GPT on with an API key on this page, then
        click a tool to filter marks after you upload.
      </p>

      <div
        className={`mb-5 panel p-4 max-w-3xl ${
          gptStatus?.available ? 'border-earth-700' : 'border-gray-800'
        }`}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            <Sparkles
              className={`w-5 h-5 mt-0.5 shrink-0 ${
                gptStatus?.available ? 'text-earth-400' : 'text-gray-500'
              }`}
            />
            <div>
              <p className="text-sm font-medium">
                {gptStatus?.available ? 'GPT correction is on' : 'Built-in checker only'}
                {gptStatus?.available && gptStatus.model ? (
                  <span className="text-gray-500 font-normal"> · {gptStatus.model}</span>
                ) : null}
                {gptStatus?.key_hint ? (
                  <span className="text-gray-500 font-normal"> · {gptStatus.key_hint}</span>
                ) : null}
              </p>
              <p className="text-xs text-gray-400 mt-1">
                {gptStatus?.note ||
                  'Paste an OpenAI API key here to turn GPT on for these tools.'}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {gptStatus?.available ? (
              <>
                <button
                  type="button"
                  className="btn-secondary text-sm"
                  onClick={() => {
                    setShowKeyForm((open) => !open);
                    setGptError('');
                    setGptMessage('');
                  }}
                >
                  Change API key
                </button>
                <button
                  type="button"
                  className="btn-secondary text-sm"
                  disabled={gptBusy}
                  onClick={() => void saveGpt(false)}
                >
                  Turn GPT off
                </button>
              </>
            ) : (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="btn-primary text-sm inline-flex items-center gap-2"
                  onClick={() => {
                    setShowKeyForm(true);
                    setGptError('');
                    setGptMessage('');
                  }}
                >
                  <KeyRound className="w-4 h-4" />
                  API key · Turn GPT on
                </button>
                {gptStatus?.configured ? (
                  <button
                    type="button"
                    className="btn-secondary text-sm"
                    disabled={gptBusy}
                    onClick={() => void saveGpt(true)}
                  >
                    Turn GPT on with saved key
                  </button>
                ) : null}
              </div>
            )}
          </div>
        </div>
        {showKeyForm && (
          <form
            className="mt-4 space-y-3 border-t border-gray-800 pt-4"
            onSubmit={(e) => {
              e.preventDefault();
              void saveGpt(true, true);
            }}
          >
            <label className="block text-sm text-gray-300" htmlFor="openai-api-key">
              OpenAI API key
            </label>
            <input
              id="openai-api-key"
              type="password"
              autoComplete="off"
              className="input-field"
              placeholder="sk-..."
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              required
            />
            <label className="block text-sm text-gray-300" htmlFor="openai-model">
              Model
            </label>
            <input
              id="openai-model"
              className="input-field"
              value={gptModel}
              onChange={(e) => setGptModel(e.target.value)}
              placeholder="gpt-4o-mini"
            />
            <p className="text-xs text-gray-500">
              The key is stored for your account on this server and used only for English
              review. Get a key from platform.openai.com.
            </p>
            <div className="flex flex-wrap gap-2">
              <button type="submit" className="btn-primary text-sm" disabled={gptBusy || !apiKey.trim()}>
                {gptBusy ? 'Checking key…' : 'Save and turn GPT on'}
              </button>
              {gptStatus?.configured && !gptStatus.available ? (
                <button
                  type="button"
                  className="btn-secondary text-sm"
                  disabled={gptBusy}
                  onClick={() => void saveGpt(true)}
                >
                  Turn GPT on with saved key
                </button>
              ) : null}
              <button
                type="button"
                className="btn-secondary text-sm"
                onClick={() => {
                  setShowKeyForm(false);
                  setApiKey('');
                  setGptError('');
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
        {gptBusy && !showKeyForm && <p className="text-earth-400 text-sm mt-3">Updating GPT…</p>}
        {gptError && <p className="text-red-400 text-sm mt-3">{gptError}</p>}
        {gptMessage && !gptError && <p className="text-emerald-400 text-sm mt-3">{gptMessage}</p>}
      </div>

      <div className="space-y-4 mb-6">
        {groupedTools.map((group) => (
          <div key={group.id}>
            <h3 className="text-xs uppercase tracking-wide text-gray-500 mb-2">{group.label}</h3>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
              {group.tools.map((tool) => {
                const count = counts[tool.id] || 0;
                const active = filter === tool.id;
                return (
                  <button
                    key={tool.id}
                    type="button"
                    onClick={() => setFilter(active ? 'all' : tool.id)}
                    className={`text-left rounded-lg border p-3 transition-colors ${
                      active
                        ? 'border-earth-500 bg-gray-800'
                        : count > 0
                          ? 'border-amber-900/60 bg-gray-900/70 hover:border-gray-600'
                          : 'border-gray-800 bg-gray-900/40 hover:border-gray-600'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-sm font-medium text-gray-100">{tool.label}</span>
                      <span
                        className={`text-[11px] px-1.5 py-0.5 rounded ${
                          count > 0 ? 'bg-amber-900/70 text-amber-200' : 'bg-gray-800 text-gray-500'
                        }`}
                      >
                        {result ? count : '—'}
                      </span>
                    </div>
                    <p className="text-xs text-gray-400 mt-1 leading-snug">{tool.description}</p>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

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
          Word (.docx) is preferred. PDF and plain text are also accepted. All tools in this
          section run on the file; GPT adds extra corrections when configured.
        </p>
      </form>
      {busy && <p className="text-earth-400 text-sm mt-3">Reviewing the document…</p>}
      {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

      {result && (
        <div className="mt-6 space-y-4">
          <div className="panel p-4 flex flex-wrap gap-4 items-start justify-between">
            <div>
              <p className="font-medium">{result.filename}</p>
              {result.summary.score != null && (
                <p className="text-2xl font-semibold text-earth-400 mt-2">
                  {result.summary.score}/100
                  {result.summary.band ? <span className="text-sm text-gray-400 ml-2">{result.summary.band}</span> : null}
                </p>
              )}
              <p className="text-sm text-gray-300 mt-2">{result.summary.verdict || result.engine_note}</p>
              <p className="text-xs text-gray-500 mt-2">
                {result.engine_note} · {result.summary.paragraph_count} paragraphs ·{' '}
                {result.summary.issue_count} suggestions
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
                  {categoryLabel(key, catalogTools)} ({count})
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
                      <span className="text-xs text-earth-400">{categoryLabel(issue.category, catalogTools)}</span>
                      <span className="flex items-center gap-2">
                        {issue.source === 'openai' ? (
                          <span className="text-[10px] uppercase text-earth-300">GPT</span>
                        ) : (
                          <span className="text-[10px] uppercase text-gray-500">built-in</span>
                        )}
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
                      </span>
                    </div>
                    <p className="text-sm text-red-200 line-through decoration-red-400/80">
                      {issue.quote}
                    </p>
                    {(issue.rewrite || issue.suggestion) && (
                      <p className="text-sm text-emerald-300 mt-1">{issue.rewrite || issue.suggestion}</p>
                    )}
                    {issue.rewrite && issue.suggestion && issue.rewrite !== issue.suggestion && (
                      <p className="text-xs text-gray-400 mt-1">{issue.suggestion}</p>
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
