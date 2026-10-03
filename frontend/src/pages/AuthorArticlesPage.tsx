import { useEffect, useState } from 'react';
import { Minus, Plus } from 'lucide-react';
import { citationApi } from '@/services/api';
import { isFullAdmin, useAuthStore } from '@/store/authStore';

type Wing = 'in_process' | 'published';

interface JournalOption {
  id?: number | null;
  name: string;
  abbreviation?: string;
}

interface ReviewRound {
  round: number;
  sent_date?: string | null;
  received_date?: string | null;
}

interface FieldChange {
  field: string;
  label: string;
  previous: string;
  new: string;
}

interface Modification {
  mod_number: number;
  changed_at: string;
  account: string;
  account_username?: string;
  account_email?: string;
  account_name?: string;
  changes: FieldChange[];
  snapshot?: Partial<AuthorRow> & { review_rounds?: ReviewRound[] };
}

interface AuthorRow {
  id: number;
  wing: Wing;
  journal_id?: number | null;
  journal_name?: string | null;
  journal_title?: string | null;
  ojs_number: string;
  title: string;
  author_names: string;
  author_emails: string;
  email_sent_date?: string | null;
  plagiarism: string;
  orcid_id: string;
  received_date?: string | null;
  review_rounds?: ReviewRound[];
  accepted_date?: string | null;
  galley_sent_date?: string | null;
  galley_received_date?: string | null;
  publish_date?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  original_snapshot?: Partial<AuthorRow> & { review_rounds?: ReviewRound[] };
  modifications?: Modification[];
}

const emptyRound = (round = 1): ReviewRound => ({ round, sent_date: '', received_date: '' });

const emptyForm = {
  journal_key: '',
  ojs_number: '',
  title: '',
  author_names: '',
  author_emails: '',
  email_sent_date: '',
  plagiarism: '',
  orcid_id: '',
  received_date: '',
  review_rounds: [emptyRound(1)],
  accepted_date: '',
  galley_sent_date: '',
  galley_received_date: '',
  publish_date: '',
};

function roundsFrom(row: AuthorRow): ReviewRound[] {
  const rounds = (row.review_rounds || []).map((item, index) => ({
    round: item.round || index + 1,
    sent_date: item.sent_date || '',
    received_date: item.received_date || '',
  }));
  return rounds.length ? rounds : [emptyRound(1)];
}

function journalLabel(journal: JournalOption) {
  return journal.name || journal.abbreviation || '';
}

function rowJournalKey(row: AuthorRow, journals: JournalOption[]) {
  if (row.journal_id) {
    const match = journals.find((journal) => journal.id === row.journal_id);
    return match ? journalKey(match) : `id:${row.journal_id}`;
  }
  const title = (row.journal_title || row.journal_name || '').trim();
  if (!title) return '';
  const lower = title.toLowerCase();
  const match = journals.find(
    (journal) =>
      (journal.abbreviation || '').toLowerCase() === lower || journal.name.toLowerCase() === lower,
  );
  return match ? journalKey(match) : `name:${title}`;
}

function rowToForm(row: AuthorRow, journals: JournalOption[]) {
  return {
    journal_key: rowJournalKey(row, journals),
    ojs_number: row.ojs_number || '',
    title: row.title || '',
    author_names: row.author_names || '',
    author_emails: row.author_emails || '',
    email_sent_date: row.email_sent_date || '',
    plagiarism: row.plagiarism || '',
    orcid_id: row.orcid_id || '',
    received_date: row.received_date || '',
    review_rounds: roundsFrom(row),
    accepted_date: row.accepted_date || '',
    galley_sent_date: row.galley_sent_date || '',
    galley_received_date: row.galley_received_date || '',
    publish_date: row.publish_date || '',
  };
}

function formatDay(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

function journalKey(journal: JournalOption) {
  if (journal.id) return `id:${journal.id}`;
  return `name:${journal.name || journal.abbreviation || ''}`;
}

function parseJournalKey(key: string): { journal_id: number | null; journal_title: string } {
  if (key.startsWith('id:')) {
    const id = Number(key.slice(3));
    return { journal_id: Number.isFinite(id) ? id : null, journal_title: '' };
  }
  if (key.startsWith('name:')) return { journal_id: null, journal_title: key.slice(5) };
  if (key.startsWith('abbr:')) return { journal_id: null, journal_title: key.slice(5) };
  return { journal_id: null, journal_title: key };
}

function applySnapshot(row: AuthorRow, snap?: Partial<AuthorRow> | null): AuthorRow {
  if (!snap || Object.keys(snap).length === 0) return row;
  return {
    ...row,
    journal_id: (snap.journal_id as number | null | undefined) ?? row.journal_id,
    journal_name: snap.journal_name ?? snap.journal_title ?? row.journal_name,
    journal_title: snap.journal_title ?? row.journal_title,
    ojs_number: snap.ojs_number ?? row.ojs_number,
    title: snap.title ?? row.title,
    author_names: snap.author_names ?? row.author_names,
    author_emails: snap.author_emails ?? row.author_emails,
    email_sent_date: snap.email_sent_date ?? row.email_sent_date,
    plagiarism: snap.plagiarism ?? row.plagiarism,
    orcid_id: snap.orcid_id ?? row.orcid_id,
    received_date: snap.received_date ?? row.received_date,
    review_rounds: snap.review_rounds ?? row.review_rounds,
    accepted_date: snap.accepted_date ?? row.accepted_date,
    galley_sent_date: snap.galley_sent_date ?? row.galley_sent_date,
    galley_received_date: snap.galley_received_date ?? row.galley_received_date,
    publish_date: snap.publish_date ?? row.publish_date,
  };
}

type DisplayRow = {
  key: string;
  article: AuthorRow;
  data: AuthorRow;
  label: string;
  dated: string | null;
  isOriginal: boolean;
};

function displayRows(row: AuthorRow): DisplayRow[] {
  const original = applySnapshot(row, row.original_snapshot);
  const out: DisplayRow[] = [
    {
      key: `${row.id}-original`,
      article: row,
      data: original,
      label: 'Original',
      dated: row.created_at || null,
      isOriginal: true,
    },
  ];
  for (const mod of row.modifications || []) {
    if (!mod.snapshot || Object.keys(mod.snapshot).length === 0) continue;
    out.push({
      key: `${row.id}-mod-${mod.mod_number}`,
      article: row,
      data: applySnapshot(row, mod.snapshot),
      label: `Modification ${mod.mod_number}`,
      dated: mod.changed_at,
      isOriginal: false,
    });
  }
  return out;
}

export default function AuthorArticlesPage({ wing }: { wing: Wing }) {
  const admin = isFullAdmin(useAuthStore((s) => s.user));
  const inProcess = wing === 'in_process';
  const [journals, setJournals] = useState<JournalOption[]>([]);
  const [rows, setRows] = useState<AuthorRow[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(inProcess);


  const load = async () => {
    const [{ data }, journalsRes] = await Promise.all([
      citationApi.authorArticles.list(wing),
      citationApi.authorArticles.journals().catch(() => ({ data: [] as JournalOption[] })),
    ]);
    setRows(data as AuthorRow[]);
    setJournals((journalsRes.data || []) as JournalOption[]);
  };

  useEffect(() => {
    setForm(emptyForm);
    setEditingId(null);
    setShowForm(inProcess);
    setMsg('');
    setError('');
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wing]);

  const payload = () => {
    const selected = journals.find((journal) => journalKey(journal) === form.journal_key);
    const parsed = parseJournalKey(form.journal_key);
    return {
      wing,
      journal_id: parsed.journal_id,
      journal_title: parsed.journal_title || selected?.name || selected?.abbreviation || '',
      ojs_number: form.ojs_number,
      title: form.title,
      author_names: form.author_names,
      author_emails: form.author_emails,
      email_sent_date: form.email_sent_date || null,
      plagiarism: form.plagiarism,
      orcid_id: form.orcid_id,
      received_date: form.received_date || null,
      review_rounds: form.review_rounds.map((round, index) => ({
        round: index + 1,
        sent_date: round.sent_date || null,
        received_date: round.received_date || null,
      })),
      accepted_date: form.accepted_date || null,
      galley_sent_date: form.galley_sent_date || null,
      galley_received_date: form.galley_received_date || null,
      publish_date: form.publish_date || null,
    };
  };

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg('');
    setError('');
    try {
      if (editingId) {
        await citationApi.authorArticles.update(editingId, payload());
        setMsg('Details saved as a new modification row, with the date of this change.');
      } else {
        await citationApi.authorArticles.create(payload());
        setMsg('Article saved.');
      }
      setForm(emptyForm);
      setEditingId(null);
      if (!inProcess) setShowForm(false);
      await load();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Could not save that article.';
      setError(String(detail));
    } finally {
      setBusy(false);
    }
  };

  const addDetails = async (row: AuthorRow) => {
    const [{ data }, journalsRes] = await Promise.all([
      citationApi.authorArticles.list(wing),
      citationApi.authorArticles.journals().catch(() => ({ data: [] as JournalOption[] })),
    ]);
    const latestList = (data || []) as AuthorRow[];
    const catalog = (journalsRes.data || []) as JournalOption[];
    setRows(latestList);
    setJournals(catalog);
    const latest = latestList.find((item) => item.id === row.id) || row;
    setForm(rowToForm(latest, catalog));
    setEditingId(row.id);
    setShowForm(true);
    setMsg('');
    setError('');
    window.setTimeout(() => {
      document.getElementById('author-article-form')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);
  };

  const remove = async (row: AuthorRow) => {
    if (!admin) return;
    setBusy(true);
    setError('');
    try {
      await citationApi.authorArticles.remove(row.id);
      if (editingId === row.id) {
        setEditingId(null);
        setForm(emptyForm);
      }
      await load();
      setMsg('Removed by admin.');
    } catch {
      setError('Could not remove that article.');
    } finally {
      setBusy(false);
    }
  };

  const move = async (row: AuthorRow, next: Wing) => {
    setBusy(true);
    setError('');
    try {
      await citationApi.authorArticles.update(row.id, { wing: next });
      await load();
      setMsg(next === 'published' ? 'Moved to published articles.' : 'Moved back to under process.');
    } catch {
      setError('Could not move that article.');
    } finally {
      setBusy(false);
    }
  };

  const downloadTemplate = async () => {
    const { data } = await citationApi.authorArticles.template();
    const blob = data instanceof Blob ? data : new Blob([data]);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'author-database-template.xlsx';
    a.click();
    URL.revokeObjectURL(url);
  };

  const importExcel = async (file: File) => {
    setBusy(true);
    setMsg('');
    setError('');
    try {
      const { data } = await citationApi.authorArticles.importFile(file, wing);
      const extra = data.errors?.length ? ` ${data.errors.slice(0, 3).join(' ')}` : '';
      setMsg(
        `Excel import: ${data.created} added, ${data.updated} updated, ${data.skipped} skipped.${extra}`,
      );
      await load();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Could not import that Excel file.';
      setError(String(detail));
    } finally {
      setBusy(false);
    }
  };

  const field = (key: keyof typeof emptyForm, value: string | number | '') => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const setRound = (index: number, key: 'sent_date' | 'received_date', value: string) => {
    setForm((prev) => ({
      ...prev,
      review_rounds: prev.review_rounds.map((round, idx) =>
        idx === index ? { ...round, [key]: value } : round,
      ),
    }));
  };

  const addRound = () => {
    setForm((prev) => ({
      ...prev,
      review_rounds: [...prev.review_rounds, emptyRound(prev.review_rounds.length + 1)],
    }));
  };

  const removeRound = (index: number) => {
    setForm((prev) => ({
      ...prev,
      review_rounds:
        prev.review_rounds.length === 1
          ? prev.review_rounds
          : prev.review_rounds.filter((_, idx) => idx !== index).map((round, idx) => ({ ...round, round: idx + 1 })),
    }));
  };

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">
        {inProcess ? 'Under process articles' : 'Published articles'}
      </h2>
      <p className="text-gray-400 text-sm mb-4 max-w-4xl">
        {inProcess
          ? 'Add or update articles. Users cannot delete rows. Add details reopens this article so you can save a new modification row with the date of the change.'
          : 'Published records keep the original row and every modification made while the article was under process. Users can update fields but cannot delete.'}
      </p>
      {msg && <p className="text-earth-400 text-sm mb-3">{msg}</p>}
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      <div className="flex flex-wrap gap-2 mb-4">
        {inProcess && !showForm && (
          <button className="btn-primary" type="button" onClick={() => setShowForm(true)}>
            Add article
          </button>
        )}
        {!inProcess && (
          <button className="btn-secondary" type="button" onClick={() => setShowForm((v) => !v)}>
            {showForm ? 'Hide form' : 'Add published article'}
          </button>
        )}
        <button className="btn-secondary" type="button" disabled={busy} onClick={() => void downloadTemplate()}>
          Download Excel template
        </button>
        <label className="btn-secondary cursor-pointer">
          Import Excel
          <input
            type="file"
            className="hidden"
            accept=".xlsx,.xlsm,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.currentTarget.value = '';
              if (file) void importExcel(file);
            }}
          />
        </label>
      </div>

      {showForm && (
        <form className="panel p-4 mb-6 grid gap-3 md:grid-cols-2" onSubmit={(e) => void save(e)}>
          <h3 className="md:col-span-2 text-sm font-medium" id="author-article-form">
            {editingId ? 'Add details' : inProcess ? 'Save under process article' : 'Save published article'}
          </h3>
          <label className="text-sm text-gray-400">
            Select journal
            <select
              className="input-field mt-1"
              value={form.journal_key}
              onChange={(e) => field('journal_key', e.target.value)}
            >
              <option value="">Select journal</option>
              {journals.map((journal) => (
                <option key={journalKey(journal)} value={journalKey(journal)}>
                  {journalLabel(journal)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm text-gray-400">
            OJS number
            <input
              className="input-field mt-1"
              value={form.ojs_number}
              onChange={(e) => field('ojs_number', e.target.value)}
            />
          </label>
          <label className="text-sm text-gray-400 md:col-span-2">
            Title
            <input className="input-field mt-1" value={form.title} onChange={(e) => field('title', e.target.value)} />
          </label>
          <label className="text-sm text-gray-400">
            Author names
            <textarea
              className="input-field mt-1 min-h-[4.5rem]"
              value={form.author_names}
              onChange={(e) => field('author_names', e.target.value)}
              placeholder="One name per line, or separated by semicolons"
            />
          </label>
          <div className="space-y-3">
            <label className="text-sm text-gray-400 block">
              Email addresses of authors
              <textarea
                className="input-field mt-1 min-h-[4.5rem]"
                value={form.author_emails}
                onChange={(e) => field('author_emails', e.target.value)}
                placeholder="Matching order with author names"
              />
            </label>
            <label className="text-sm text-gray-400 block">
              Email sent date
              <input
                className="input-field mt-1"
                type="date"
                value={form.email_sent_date}
                onChange={(e) => field('email_sent_date', e.target.value)}
              />
            </label>
          </div>
          <label className="text-sm text-gray-400">
            Plagiarism
            <input
              className="input-field mt-1"
              value={form.plagiarism}
              onChange={(e) => field('plagiarism', e.target.value)}
              placeholder="e.g. 11%"
            />
          </label>
          <label className="text-sm text-gray-400">
            ORCID ID
            <input className="input-field mt-1" value={form.orcid_id} onChange={(e) => field('orcid_id', e.target.value)} />
          </label>
          <label className="text-sm text-gray-400">
            Receive date
            <input
              className="input-field mt-1"
              type="date"
              value={form.received_date}
              onChange={(e) => field('received_date', e.target.value)}
            />
          </label>
          <div className="md:col-span-2 space-y-3">
            {form.review_rounds.map((round, index) => (
              <div key={round.round} className="border border-gray-800 rounded-md p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-gray-200">Round {index + 1}</p>
                  <div className="flex items-center gap-1">
                    {index === form.review_rounds.length - 1 && (
                      <button
                        type="button"
                        className="text-gray-400 hover:text-white p-1"
                        onClick={addRound}
                        title={`Add round ${form.review_rounds.length + 1}`}
                      >
                        <Plus className="w-4 h-4" />
                      </button>
                    )}
                    {index > 0 && (
                      <button
                        type="button"
                        className="text-gray-400 hover:text-white p-1"
                        onClick={() => removeRound(index)}
                        title="Remove this round"
                      >
                        <Minus className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <label className="text-sm text-gray-400">
                    Review sent date
                    <input
                      className="input-field mt-1"
                      type="date"
                      value={round.sent_date || ''}
                      onChange={(e) => setRound(index, 'sent_date', e.target.value)}
                    />
                  </label>
                  <label className="text-sm text-gray-400">
                    Review receive date
                    <input
                      className="input-field mt-1"
                      type="date"
                      value={round.received_date || ''}
                      onChange={(e) => setRound(index, 'received_date', e.target.value)}
                    />
                  </label>
                </div>
              </div>
            ))}
            <button
              type="button"
              className="btn-secondary inline-flex items-center gap-2"
              onClick={addRound}
            >
              <Plus className="w-4 h-4" />
              Add round {form.review_rounds.length + 1}
            </button>
          </div>
          <label className="text-sm text-gray-400">
            Acceptance date
            <input
              className="input-field mt-1"
              type="date"
              value={form.accepted_date}
              onChange={(e) => field('accepted_date', e.target.value)}
            />
          </label>
          <label className="text-sm text-gray-400">
            Galley sent date
            <input
              className="input-field mt-1"
              type="date"
              value={form.galley_sent_date}
              onChange={(e) => field('galley_sent_date', e.target.value)}
            />
          </label>
          <label className="text-sm text-gray-400">
            Galley received date
            <input
              className="input-field mt-1"
              type="date"
              value={form.galley_received_date}
              onChange={(e) => field('galley_received_date', e.target.value)}
            />
          </label>
          <label className="text-sm text-gray-400">
            Publish date
            <input
              className="input-field mt-1"
              type="date"
              value={form.publish_date}
              onChange={(e) => field('publish_date', e.target.value)}
            />
          </label>
          <div className="md:col-span-2 flex flex-wrap gap-2">
            <button className="btn-primary" type="submit" disabled={busy}>
              {busy ? 'Saving…' : 'Save article'}
            </button>
            {editingId && (
              <button
                className="btn-secondary"
                type="button"
                onClick={() => {
                  setEditingId(null);
                  setForm(emptyForm);
                }}
              >
                Cancel
              </button>
            )}
          </div>
        </form>
      )}

      <div className="panel overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b border-gray-800">
              <th className="py-2 pr-3">Article</th>
              <th className="py-2 pr-3">Title</th>
              <th className="py-2 pr-3">Authors</th>
              <th className="py-2 pr-3">Email sent date</th>
              <th className="py-2 pr-3">Plagiarism</th>
              <th className="py-2 pr-3">ORCID</th>
              <th className="py-2 pr-3">Review rounds</th>
              <th className="py-2 pr-3">Dates</th>
              <th className="py-2 pr-3" />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td className="py-4 text-gray-500" colSpan={9}>
                  {inProcess
                    ? 'No under process articles yet. Add one or import an Excel file.'
                    : 'No published articles yet. Move a finished record from Under process or import Excel.'}
                </td>
              </tr>
            )}
            {rows.flatMap((row) =>
              displayRows(row).map((ver) => (
              <tr key={ver.key} className="border-b border-gray-800/80 align-top">
                <td className="py-3 pr-3 whitespace-nowrap min-w-[12rem]">
                  <p className={ver.isOriginal ? 'text-gray-200 font-medium' : 'text-earth-400 font-medium'}>{ver.label}</p>
                  <p className="text-xs text-gray-500">{formatDay(ver.dated)}</p>
                  <p className="mt-1">{ver.data.ojs_number || '—'}</p>
                  {ver.data.journal_name ? (
                    <p className="text-xs text-gray-500 max-w-[14rem] whitespace-normal">{ver.data.journal_name}</p>
                  ) : null}
                </td>
                <td className="py-3 pr-3 min-w-[12rem]">{ver.data.title || '—'}</td>
                <td className="py-3 pr-3 min-w-[10rem]">
                  <p>{ver.data.author_names || '—'}</p>
                  <p className="text-xs text-gray-500">{ver.data.author_emails}</p>
                </td>
                <td className="py-3 pr-3">{ver.data.email_sent_date || '—'}</td>
                <td className="py-3 pr-3">{ver.data.plagiarism || '—'}</td>
                <td className="py-3 pr-3">{ver.data.orcid_id || '—'}</td>
                <td className="py-3 pr-3 text-xs text-gray-400 whitespace-nowrap">
                  {(ver.data.review_rounds || []).map((round) => (
                    <p key={round.round}>
                      R{round.round}: sent {round.sent_date || '—'} / rec {round.received_date || '—'}
                    </p>
                  ))}
                  {(ver.data.review_rounds || []).length === 0 ? '—' : null}
                </td>
                <td className="py-3 pr-3 text-xs text-gray-400 whitespace-nowrap">
                  <p>Acc {ver.data.accepted_date || '—'}</p>
                  <p>Gal sent {ver.data.galley_sent_date || '—'}</p>
                  <p>Gal rec {ver.data.galley_received_date || '—'}</p>
                  <p>Pub {ver.data.publish_date || '—'}</p>
                </td>
                <td className="py-3">
                  {ver.isOriginal ? (
                  <div className="flex flex-wrap gap-2">
                    {inProcess && (
                      <button className="btn-primary" type="button" disabled={busy} onClick={() => addDetails(row)}>
                        Add details
                      </button>
                    )}
                    {inProcess ? (
                      <button
                        className="btn-secondary"
                        type="button"
                        disabled={busy}
                        onClick={() => void move(row, 'published')}
                      >
                        Move to published
                      </button>
                    ) : (
                      <button
                        className="btn-secondary"
                        type="button"
                        disabled={busy}
                        onClick={() => void move(row, 'in_process')}
                      >
                        Back to under process
                      </button>
                    )}
                    {admin && (
                      <button className="btn-secondary" type="button" disabled={busy} onClick={() => void remove(row)}>
                        Remove
                      </button>
                    )}
                  </div>
                  ) : null}
                </td>
              </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
