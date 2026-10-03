import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { FolderOpen, ShieldAlert } from 'lucide-react';
import { citationApi } from '@/services/api';
import { hasAuthorWing, useAuthStore } from '@/store/authStore';

interface JournalOption {
  id?: number | null;
  name: string;
  abbreviation?: string;
}

interface IssueArticle {
  id: number;
  wing: string;
  journal_title?: string;
  journal_name?: string | null;
  ojs_number: string;
  title: string;
  author_names: string;
  author_emails?: string;
}

interface Overlap {
  author: string;
  matched_as: string;
  issue_article_id: number;
  issue_ojs: string;
  issue_title: string;
  reason: string;
}

function journalKey(journal: JournalOption) {
  return journal.name || journal.abbreviation || '';
}

function journalLabel(journal: JournalOption) {
  if (journal.abbreviation && journal.name && journal.abbreviation !== journal.name) {
    return `${journal.abbreviation} — ${journal.name}`;
  }
  return journal.name || journal.abbreviation || '';
}

function splitAuthors(raw?: string) {
  return (raw || '')
    .split(/[\n;|]+|(?:\s+and\s+)|(?:\s*&\s*)/i)
    .map((item) => item.trim().replace(/^,+|,+$/g, ''))
    .filter(Boolean);
}

function authorKey(name: string) {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

function uniqueAuthors(rows: IssueArticle[]) {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const row of rows) {
    for (const name of splitAuthors(row.author_names)) {
      const key = authorKey(name);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push(name);
    }
  }
  return out;
}

function articleLabel(row: IssueArticle) {
  return `${row.ojs_number || `No OJS #${row.id}`} — ${row.title || 'Untitled'}`;
}

export default function AuthorSanitizationPage() {
  const user = useAuthStore((s) => s.user);
  const canPublish = hasAuthorWing(user, 'published');
  const [journals, setJournals] = useState<JournalOption[]>([]);
  const [journal, setJournal] = useState('');
  const [published, setPublished] = useState<IssueArticle[]>([]);
  const [scheduled, setScheduled] = useState<IssueArticle[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [dropId, setDropId] = useState<number | ''>('');
  const [candidateId, setCandidateId] = useState<number | ''>('');
  const [result, setResult] = useState<{
    allowed: boolean;
    message: string;
    overlaps: Overlap[];
  } | null>(null);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const applyPayload = (data: {
    article_ids?: number[];
    published?: IssueArticle[];
    scheduled?: IssueArticle[];
  }) => {
    setPublished(data.published || []);
    setScheduled(data.scheduled || []);
    setSelected(data.article_ids || []);
  };

  const load = async (journalTitle = journal) => {
    const [journalsRes, dataRes] = await Promise.all([
      citationApi.authorArticles.journals().catch(() => ({ data: [] as JournalOption[] })),
      citationApi.authorArticles.sanitization(journalTitle || undefined),
    ]);
    setJournals((journalsRes.data || []) as JournalOption[]);
    applyPayload(dataRes.data as { article_ids?: number[]; published?: IssueArticle[]; scheduled?: IssueArticle[] });
  };

  useEffect(() => {
    void load('').catch(() => setError('Could not load published and under-process articles.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const changeJournal = async (next: string) => {
    setJournal(next);
    setResult(null);
    setCandidateId('');
    setDropId('');
    setMsg('');
    setError('');
    setBusy(true);
    try {
      await load(next);
    } catch {
      setError('Could not load that journal’s current issue.');
    } finally {
      setBusy(false);
    }
  };

  const folderRows = useMemo(
    () => selected.map((id) => published.find((row) => row.id === id)).filter((row): row is IssueArticle => Boolean(row)),
    [published, selected],
  );
  const availablePublished = useMemo(
    () => published.filter((row) => !selected.includes(row.id)),
    [published, selected],
  );
  const authors = useMemo(() => uniqueAuthors(folderRows), [folderRows]);
  const candidate = useMemo(
    () => scheduled.find((row) => row.id === candidateId) || null,
    [scheduled, candidateId],
  );

  const persistFolder = async (ids: number[], quiet = false) => {
    const { data } = await citationApi.authorArticles.saveSanitization({
      journal_title: journal,
      label: 'Current issue',
      article_ids: ids,
    });
    applyPayload(data);
    if (!quiet) {
      setMsg(
        ids.length
          ? `Current issue folder now has ${ids.length} published article${ids.length === 1 ? '' : 's'}.`
          : 'Current issue folder cleared.',
      );
    }
  };

  const dropIntoFolder = async () => {
    if (!dropId) {
      setError('Select a published article to drop into the current issue.');
      return;
    }
    const ids = selected.includes(dropId) ? selected : [...selected, dropId];
    setSelected(ids);
    setDropId('');
    setResult(null);
    setError('');
    if (!canPublish) return;
    setBusy(true);
    try {
      await persistFolder(ids);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Could not add that published article to the current issue.';
      setError(String(detail));
    } finally {
      setBusy(false);
    }
  };

  const removeFromFolder = async (id: number) => {
    const ids = selected.filter((item) => item !== id);
    setSelected(ids);
    setResult(null);
    if (!canPublish) return;
    setBusy(true);
    setError('');
    try {
      await persistFolder(ids, true);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Could not update the current issue folder.';
      setError(String(detail));
    } finally {
      setBusy(false);
    }
  };

  const saveIssue = async () => {
    setBusy(true);
    setMsg('');
    setError('');
    try {
      await persistFolder(selected);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Could not save the current issue.';
      setError(String(detail));
    } finally {
      setBusy(false);
    }
  };

  const check = async () => {
    if (!candidateId) {
      setError('Select an under-process article as the scheduled article.');
      return;
    }
    setBusy(true);
    setMsg('');
    setError('');
    try {
      const { data } = await citationApi.authorArticles.checkSanitization({
        article_id: candidateId,
        journal_title: journal,
        article_ids: selected,
      });
      setResult({
        allowed: Boolean(data.allowed),
        message: data.message || '',
        overlaps: data.overlaps || [],
      });
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Could not check that article.';
      setError(String(detail));
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    if (!candidateId) return;
    setBusy(true);
    setMsg('');
    setError('');
    try {
      const { data } = await citationApi.authorArticles.publishSanitization(Number(candidateId), {
        journal_title: journal,
        article_ids: selected,
      });
      setResult({
        allowed: true,
        message: data.message || 'Published into the current issue.',
        overlaps: [],
      });
      setMsg(data.message || 'Published into the current issue.');
      setCandidateId('');
      await load(journal);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Could not publish that article.';
      setError(String(detail));
      setResult({ allowed: false, message: String(detail), overlaps: [] });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">
        <Link className="text-earth-400" to="/authors">
          Author database
        </Link>
        {' / sanitization'}
      </p>
      <h2 className="text-2xl font-semibold mb-2 inline-flex items-center gap-2">
        <ShieldAlert className="w-6 h-6 text-earth-400" />
        Issue sanitization
      </h2>
      <p className="text-gray-400 text-sm mb-4 max-w-4xl">
        Current issue is a folder of published articles. The authors already in that folder are the
        checkpoint. The scheduled article is chosen from under-process articles. An author may appear
        only once in the current issue.
      </p>
      {msg && <p className="text-earth-400 text-sm mb-3">{msg}</p>}
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      <label className="text-sm text-gray-400 block mb-6 max-w-xl">
        Journal
        <select className="input-field mt-1" value={journal} onChange={(e) => void changeJournal(e.target.value)}>
          <option value="">All journals</option>
          {journals.map((item) => (
            <option key={journalKey(item)} value={item.name || item.abbreviation || ''}>
              {journalLabel(item)}
            </option>
          ))}
        </select>
      </label>

      <section className="panel p-4 mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          <div>
            <h3 className="text-sm font-medium inline-flex items-center gap-2">
              <FolderOpen className="w-4 h-4 text-earth-400" />
              Current issue
            </h3>
            <p className="text-xs text-gray-500">
              Drop published articles into this folder. The author list below is what sanitization
              checks against.
            </p>
          </div>
          {canPublish && (
            <button className="btn-primary" type="button" disabled={busy} onClick={() => void saveIssue()}>
              {busy ? 'Saving…' : 'Save current issue'}
            </button>
          )}
        </div>

        <div className="rounded-md border border-gray-800 p-3 mb-4">
          <p className="text-sm text-gray-200 mb-2">Authors in this issue</p>
          {authors.length === 0 ? (
            <p className="text-gray-500 text-sm">No authors yet. Drop published articles into the folder.</p>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {authors.map((name) => (
                <li key={authorKey(name)} className="rounded-full bg-gray-800 px-3 py-1 text-sm text-gray-100">
                  {name}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex flex-wrap gap-2 items-end mb-4">
          <label className="text-sm text-gray-400 flex-1 min-w-[16rem]">
            Drop a published article
            <select
              className="input-field mt-1"
              value={dropId}
              onChange={(e) => setDropId(e.target.value ? Number(e.target.value) : '')}
            >
              <option value="">Select from published articles</option>
              {availablePublished.map((row) => (
                <option key={row.id} value={row.id}>
                  {articleLabel(row)}
                </option>
              ))}
            </select>
          </label>
          <button className="btn-secondary" type="button" disabled={busy || !dropId} onClick={() => void dropIntoFolder()}>
            Drop into current issue
          </button>
        </div>
        {published.length === 0 ? (
          <p className="text-gray-500 text-sm">No published articles are available to drop into this issue.</p>
        ) : folderRows.length === 0 ? (
          <p className="text-gray-500 text-sm">The current issue folder is empty.</p>
        ) : (
          <div className="space-y-2">
            {folderRows.map((row) => (
              <div key={row.id} className="flex items-start justify-between gap-3 rounded-md border border-gray-800 p-3 text-sm">
                <span className="min-w-0">
                  <span className="text-gray-100 font-medium">{row.ojs_number || `No OJS #${row.id}`}</span>
                  <span className="block text-gray-300">{row.title || 'Untitled'}</span>
                  <span className="block text-gray-500 text-xs mt-1">Authors: {row.author_names || '—'}</span>
                </span>
                <button className="btn-secondary shrink-0" type="button" disabled={busy} onClick={() => void removeFromFolder(row.id)}>
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="panel p-4 mb-6">
        <h3 className="text-sm font-medium mb-1">Scheduled article</h3>
        <p className="text-xs text-gray-500 mb-3">
          Choose from under-process articles. Check whether those authors may enter the current issue.
        </p>
        <label className="text-sm text-gray-400 block max-w-xl">
          Under-process article
          <select
            className="input-field mt-1"
            value={candidateId}
            onChange={(e) => {
              setCandidateId(e.target.value ? Number(e.target.value) : '');
              setResult(null);
              setError('');
            }}
          >
            <option value="">Select scheduled article</option>
            {scheduled.map((row) => (
              <option key={row.id} value={row.id}>
                {articleLabel(row)}
              </option>
            ))}
          </select>
        </label>
        {scheduled.length === 0 && (
          <p className="text-gray-500 text-sm mt-2">No under-process articles are available to schedule.</p>
        )}
        {candidate && (
          <p className="text-sm text-gray-300 mt-3">
            Authors on this article: {candidate.author_names || '—'}
          </p>
        )}
        <div className="flex flex-wrap gap-2 mt-4">
          <button className="btn-secondary" type="button" disabled={busy || !candidateId} onClick={() => void check()}>
            Check authors
          </button>
          {canPublish && result?.allowed && (
            <button className="btn-primary" type="button" disabled={busy || !candidateId} onClick={() => void publish()}>
              Publish into current issue
            </button>
          )}
        </div>
      </section>

      {result && (
        <section className={`panel p-4 ${result.allowed ? 'border-emerald-700' : 'border-red-800'}`}>
          <p className={result.allowed ? 'text-emerald-400' : 'text-red-400'}>{result.message}</p>
          {result.overlaps.length > 0 && (
            <ul className="mt-3 space-y-2 text-sm text-gray-300">
              {result.overlaps.map((hit, index) => (
                <li key={`${hit.issue_article_id}-${index}`}>
                  {hit.reason === 'email'
                    ? `${hit.author} is already on ${hit.issue_ojs || `article #${hit.issue_article_id}`}`
                    : `${hit.author} matches ${hit.matched_as} on ${hit.issue_ojs || `article #${hit.issue_article_id}`}`}
                  {hit.issue_title ? ` (${hit.issue_title})` : ''}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
