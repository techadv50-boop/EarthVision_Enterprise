import { useEffect, useState } from 'react';
import { citationApi } from '@/services/api';
import { isCitationAdmin, useAuthStore } from '@/store/authStore';

type Wing = 'in_process' | 'published';

interface JournalOption {
  id: number;
  name: string;
  abbreviation?: string;
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
  ojs_number: string;
  title: string;
  author_names: string;
  author_emails: string;
  email_sent: boolean;
  plagiarism: string;
  orcid_id: string;
  received_date?: string | null;
  review_date?: string | null;
  accepted_date?: string | null;
  publish_date?: string | null;
  repeat_done: boolean;
  doi_in_pdf: string;
  updated_at?: string | null;
  modifications?: Modification[];
}

const emptyForm = {
  journal_id: '' as number | '',
  ojs_number: '',
  title: '',
  author_names: '',
  author_emails: '',
  email_sent: false,
  plagiarism: '',
  orcid_id: '',
  received_date: '',
  review_date: '',
  accepted_date: '',
  publish_date: '',
  repeat_done: false,
  doi_in_pdf: '',
};

function rowToForm(row: AuthorRow) {
  return {
    journal_id: row.journal_id || ('' as number | ''),
    ojs_number: row.ojs_number || '',
    title: row.title || '',
    author_names: row.author_names || '',
    author_emails: row.author_emails || '',
    email_sent: Boolean(row.email_sent),
    plagiarism: row.plagiarism || '',
    orcid_id: row.orcid_id || '',
    received_date: row.received_date || '',
    review_date: row.review_date || '',
    accepted_date: row.accepted_date || '',
    publish_date: row.publish_date || '',
    repeat_done: Boolean(row.repeat_done),
    doi_in_pdf: row.doi_in_pdf || '',
  };
}

function formatWhen(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export default function AuthorArticlesPage({ wing }: { wing: Wing }) {
  const admin = isCitationAdmin(useAuthStore((s) => s.user));
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
      citationApi.journals.list().catch(() => ({ data: [] as JournalOption[] })),
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

  const payload = () => ({
    wing,
    journal_id: form.journal_id === '' ? null : form.journal_id,
    ojs_number: form.ojs_number,
    title: form.title,
    author_names: form.author_names,
    author_emails: form.author_emails,
    email_sent: form.email_sent,
    plagiarism: form.plagiarism,
    orcid_id: form.orcid_id,
    received_date: form.received_date || null,
    review_date: form.review_date || null,
    accepted_date: form.accepted_date || null,
    publish_date: form.publish_date || null,
    repeat_done: form.repeat_done,
    doi_in_pdf: form.doi_in_pdf,
  });

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
    setForm(rowToForm(row));
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

  const field = (key: keyof typeof emptyForm, value: string | boolean | number | '') => {
    setForm((prev) => ({ ...prev, [key]: value }));
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
          {journals.length > 0 && (
            <label className="text-sm text-gray-400">
              Journal
              <select
                className="input-field mt-1"
                value={form.journal_id}
                onChange={(e) => field('journal_id', e.target.value ? Number(e.target.value) : '')}
              >
                <option value="">Select journal</option>
                {journals.map((journal) => (
                  <option key={journal.id} value={journal.id}>
                    {journal.abbreviation || journal.name}
                  </option>
                ))}
              </select>
            </label>
          )}
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
          <label className="text-sm text-gray-400">
            Email addresses of authors
            <textarea
              className="input-field mt-1 min-h-[4.5rem]"
              value={form.author_emails}
              onChange={(e) => field('author_emails', e.target.value)}
              placeholder="Matching order with author names"
            />
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-gray-300 mt-6">
            <input
              type="checkbox"
              checked={form.email_sent}
              onChange={(e) => field('email_sent', e.target.checked)}
            />
            Email sent
          </label>
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
          <label className="text-sm text-gray-400">
            Review date
            <input
              className="input-field mt-1"
              type="date"
              value={form.review_date}
              onChange={(e) => field('review_date', e.target.value)}
            />
          </label>
          <label className="text-sm text-gray-400">
            Accepted date
            <input
              className="input-field mt-1"
              type="date"
              value={form.accepted_date}
              onChange={(e) => field('accepted_date', e.target.value)}
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
          <label className="inline-flex items-center gap-2 text-sm text-gray-300 mt-6">
            <input
              type="checkbox"
              checked={form.repeat_done}
              onChange={(e) => field('repeat_done', e.target.checked)}
            />
            Repeat done
          </label>
          <label className="text-sm text-gray-400">
            DOI in PDF
            <input className="input-field mt-1" value={form.doi_in_pdf} onChange={(e) => field('doi_in_pdf', e.target.value)} />
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
              <th className="py-2 pr-3">Email sent</th>
              <th className="py-2 pr-3">Plagiarism</th>
              <th className="py-2 pr-3">ORCID</th>
              <th className="py-2 pr-3">Dates</th>
              <th className="py-2 pr-3">Repeat</th>
              <th className="py-2 pr-3">DOI in PDF</th>
              <th className="py-2 pr-3">Modifications</th>
              <th className="py-2 pr-3" />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td className="py-4 text-gray-500" colSpan={11}>
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
                <td className="py-3 pr-3">{row.email_sent ? 'Yes' : 'No'}</td>
                <td className="py-3 pr-3">{row.plagiarism || '—'}</td>
                <td className="py-3 pr-3">{row.orcid_id || '—'}</td>
                <td className="py-3 pr-3 text-xs text-gray-400 whitespace-nowrap">
                  <p>Rec {row.received_date || '—'}</p>
                  <p>Rev {row.review_date || '—'}</p>
                  <p>Acc {row.accepted_date || '—'}</p>
                  <p>Pub {row.publish_date || '—'}</p>
                </td>
                <td className="py-3 pr-3">{row.repeat_done ? 'Yes' : 'No'}</td>
                <td className="py-3 pr-3">{row.doi_in_pdf || '—'}</td>
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
