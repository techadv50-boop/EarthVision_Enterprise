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
  updated_at?: string | null;
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
  if (journal.abbreviation && journal.name && journal.abbreviation !== journal.name) {
    return `${journal.abbreviation} — ${journal.name}`;
  }
  return journal.abbreviation || journal.name;
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
  return match ? journalKey(match) : `abbr:${title}`;
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

function formatWhen(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function journalKey(journal: JournalOption) {
  if (journal.id) return `id:${journal.id}`;
  return `abbr:${journal.abbreviation || journal.name}`;
}

function parseJournalKey(key: string): { journal_id: number | null; journal_title: string } {
  if (key.startsWith('id:')) {
    const id = Number(key.slice(3));
    return { journal_id: Number.isFinite(id) ? id : null, journal_title: '' };
  }
  if (key.startsWith('abbr:')) return { journal_id: null, journal_title: key.slice(5) };
  return { journal_id: null, journal_title: key };
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
  const [openMod, setOpenMod] = useState<{ row: AuthorRow; mod: Modification } | null>(null);

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
    setOpenMod(null);
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wing]);

  const payload = () => {
    const selected = journals.find((journal) => journalKey(journal) === form.journal_key);
    const parsed = parseJournalKey(form.journal_key);
    return {
      wing,
      journal_id: parsed.journal_id,
      journal_title: parsed.journal_title || selected?.abbreviation || selected?.name || '',
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
        setMsg('Modification saved. A MOD button records who changed what, and when.');
      } else {
        await citationApi.authorArticles.create(payload());
        setMsg('Added to under process.');
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

  const edit = (row: AuthorRow) => {
    setForm(rowToForm(row, journals));
    setEditingId(row.id);
    setShowForm(true);
    setMsg('');
    setError('');
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
          ? 'Add or modify articles. Users cannot delete rows. Every saved change gets a MOD button with the date, time, account, previous value, and new value.'
          : 'Published records keep the same modification history. Users can update fields but cannot delete.'}
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
          <h3 className="md:col-span-2 text-sm font-medium">
            {editingId ? 'Modify article' : inProcess ? 'Add under process article' : 'Add published article'}
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
              {busy ? 'Saving…' : editingId ? 'Save modification' : 'Add article'}
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
              <th className="py-2 pr-3">OJS</th>
              <th className="py-2 pr-3">Title</th>
              <th className="py-2 pr-3">Authors</th>
              <th className="py-2 pr-3">Email sent date</th>
              <th className="py-2 pr-3">Plagiarism</th>
              <th className="py-2 pr-3">ORCID</th>
              <th className="py-2 pr-3">Review rounds</th>
              <th className="py-2 pr-3">Dates</th>
              <th className="py-2 pr-3">Modifications</th>
              <th className="py-2 pr-3" />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td className="py-4 text-gray-500" colSpan={10}>
                  {inProcess
                    ? 'No under process articles yet. Add one or import an Excel file.'
                    : 'No published articles yet. Move a finished record from Under process or import Excel.'}
                </td>
              </tr>
            )}
            {rows.map((row) => (
              <tr key={row.id} className="border-b border-gray-800/80 align-top">
                <td className="py-3 pr-3 whitespace-nowrap">
                  {row.ojs_number || '—'}
                  {row.journal_name ? <p className="text-xs text-gray-500">{row.journal_name}</p> : null}
                </td>
                <td className="py-3 pr-3 min-w-[12rem]">{row.title || '—'}</td>
                <td className="py-3 pr-3 min-w-[10rem]">
                  <p>{row.author_names || '—'}</p>
                  <p className="text-xs text-gray-500">{row.author_emails}</p>
                </td>
                <td className="py-3 pr-3">{row.email_sent_date || '—'}</td>
                <td className="py-3 pr-3">{row.plagiarism || '—'}</td>
                <td className="py-3 pr-3">{row.orcid_id || '—'}</td>
                <td className="py-3 pr-3 text-xs text-gray-400 whitespace-nowrap">
                  {(row.review_rounds || []).map((round) => (
                    <p key={round.round}>
                      R{round.round}: sent {round.sent_date || '—'} / rec {round.received_date || '—'}
                    </p>
                  ))}
                  {(row.review_rounds || []).length === 0 ? '—' : null}
                </td>
                <td className="py-3 pr-3 text-xs text-gray-400 whitespace-nowrap">
                  <p>Acc {row.accepted_date || '—'}</p>
                  <p>Gal sent {row.galley_sent_date || '—'}</p>
                  <p>Gal rec {row.galley_received_date || '—'}</p>
                  <p>Pub {row.publish_date || '—'}</p>
                </td>
                <td className="py-3 pr-3">
                  <div className="flex flex-wrap gap-1">
                    {(row.modifications || []).length === 0 && <span className="text-xs text-gray-500">None</span>}
                    {(row.modifications || []).map((mod) => (
                      <button
                        key={mod.mod_number}
                        className="btn-secondary text-xs px-2 py-1"
                        type="button"
                        onClick={() => setOpenMod({ row, mod })}
                      >
                        MOD {mod.mod_number}
                      </button>
                    ))}
                  </div>
                </td>
                <td className="py-3">
                  <div className="flex flex-wrap gap-2">
                    <button className="btn-secondary" type="button" disabled={busy} onClick={() => edit(row)}>
                      Modify
                    </button>
                    {inProcess ? (
                      <button
                        className="btn-primary"
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
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {openMod && (
        <div className="fixed inset-0 z-40 bg-black/70 flex items-center justify-center p-4" onClick={() => setOpenMod(null)}>
          <div className="panel max-w-lg w-full p-5" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-1">
              MOD {openMod.mod.mod_number} · {openMod.row.ojs_number || openMod.row.title || 'Article'}
            </h3>
            <p className="text-sm text-gray-400 mb-1">Date and time: {formatWhen(openMod.mod.changed_at)}</p>
            <p className="text-sm text-gray-300 mb-4">Account: {openMod.mod.account}</p>
            <div className="space-y-3 max-h-[50vh] overflow-y-auto">
              {openMod.mod.changes.map((change, idx) => (
                <div key={`${change.field}-${idx}`} className="border border-gray-800 rounded-md p-3">
                  <p className="text-sm font-medium text-earth-400">{change.label}</p>
                  <p className="text-sm text-gray-400 mt-1">Previous: {change.previous}</p>
                  <p className="text-sm text-gray-200">New: {change.new}</p>
                </div>
              ))}
            </div>
            <button className="btn-primary mt-4" type="button" onClick={() => setOpenMod(null)}>
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
