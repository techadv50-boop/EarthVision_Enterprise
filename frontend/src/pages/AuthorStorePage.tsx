import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Archive, Download, Upload } from 'lucide-react';
import { citationApi } from '@/services/api';
import { isFullAdmin, useAuthStore } from '@/store/authStore';

interface StoreJournal {
  key: string;
  name: string;
  abbreviation?: string;
  file_count: number;
}

interface StoreFile {
  id: number;
  journal_key: string;
  journal_name: string;
  original_name: string;
  content_type?: string;
  size_bytes: number;
  created_at?: string;
}

function formatSize(bytes: number) {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatWhen(value?: string) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function filenameFromHeader(header: string | undefined, fallback: string) {
  if (!header) return fallback;
  const utf = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf) {
    try {
      return decodeURIComponent(utf[1]);
    } catch {
      return utf[1];
    }
  }
  const plain = header.match(/filename="?([^";]+)"?/i);
  return plain ? plain[1] : fallback;
}

export default function AuthorStorePage() {
  const admin = isFullAdmin(useAuthStore((s) => s.user));
  const [journals, setJournals] = useState<StoreJournal[]>([]);
  const [journalKey, setJournalKey] = useState('');
  const [files, setFiles] = useState<StoreFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [downloadId, setDownloadId] = useState<number | null>(null);
  const [password, setPassword] = useState('');

  const active = journals.find((item) => item.key === journalKey) || journals[0];

  const loadJournals = async (preferred = journalKey) => {
    const { data } = await citationApi.authorArticles.storeJournals();
    const rows = (data || []) as StoreJournal[];
    setJournals(rows);
    const next = rows.find((item) => item.key === preferred)?.key || rows[0]?.key || '';
    setJournalKey(next);
    return next;
  };

  const loadFiles = async (key: string) => {
    if (!key) {
      setFiles([]);
      return;
    }
    const { data } = await citationApi.authorArticles.storeFiles(key);
    setFiles((data || []) as StoreFile[]);
  };

  useEffect(() => {
    void loadJournals('')
      .then((key) => loadFiles(key))
      .catch(() => setError('Could not load the article store.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const changeJournal = async (key: string) => {
    setJournalKey(key);
    setMsg('');
    setError('');
    setDownloadId(null);
    setPassword('');
    setBusy(true);
    try {
      await loadFiles(key);
    } catch {
      setError('Could not load articles for that journal.');
    } finally {
      setBusy(false);
    }
  };

  const upload = async (file?: File | null) => {
    if (!file || !active) return;
    setBusy(true);
    setMsg('');
    setError('');
    try {
      await citationApi.authorArticles.storeUpload(active.key, file);
      setMsg(`Stored ${file.name} under ${active.name}.`);
      await loadJournals(active.key);
      await loadFiles(active.key);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Could not upload that article.';
      setError(typeof detail === 'string' ? detail : 'Could not upload that article.');
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    if (!downloadId) return;
    setBusy(true);
    setError('');
    try {
      const res = await citationApi.authorArticles.storeDownload(downloadId, password);
      const blob = res.data as Blob;
      if (blob.type && blob.type.includes('application/json')) {
        const parsed = JSON.parse(await blob.text()) as { detail?: string };
        throw new Error(parsed.detail || 'Could not download that article.');
      }
      const name = filenameFromHeader(
        res.headers['content-disposition'],
        files.find((item) => item.id === downloadId)?.original_name || 'article',
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = name;
      link.click();
      URL.revokeObjectURL(url);
      setDownloadId(null);
      setPassword('');
      setMsg(`Downloaded ${name}.`);
    } catch (err: unknown) {
      let detail = 'Could not download that article.';
      const payload = (err as { response?: { data?: unknown } })?.response?.data;
      if (payload instanceof Blob) {
        try {
          const parsed = JSON.parse(await payload.text()) as { detail?: string };
          if (parsed.detail) detail = parsed.detail;
        } catch {
          /* keep default */
        }
      } else if (typeof payload === 'object' && payload && 'detail' in payload) {
        detail = String((payload as { detail: string }).detail);
      } else if (err instanceof Error && err.message) {
        detail = err.message;
      }
      setError(detail);
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
        {' / article store'}
      </p>
      <h2 className="text-2xl font-semibold mb-2 inline-flex items-center gap-2">
        <Archive className="w-6 h-6 text-earth-400" />
        Article store
      </h2>
      <p className="text-gray-400 text-sm mb-4 max-w-4xl">
        Each of the six journals has its own tab. Upload articles here so they can be downloaded later
        with the admin password.
      </p>
      {msg && <p className="text-earth-400 text-sm mb-3">{msg}</p>}
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      <div className="flex flex-wrap gap-2 mb-6">
        {journals.map((journal) => (
          <button
            key={journal.key}
            type="button"
            className={journal.key === active?.key ? 'btn-primary' : 'btn-secondary'}
            onClick={() => void changeJournal(journal.key)}
          >
            {journal.name}
            {journal.file_count ? ` (${journal.file_count})` : ''}
          </button>
        ))}
      </div>

      {active && (
        <section className="panel p-4 mb-6">
          <h3 className="text-lg font-semibold">{active.name}</h3>
          <p className="text-xs text-gray-500 mb-4">
            {active.abbreviation && active.abbreviation !== active.name ? `${active.abbreviation} · ` : ''}
            Upload a PDF or Word article for later use.
          </p>
          <label className="btn-primary inline-flex items-center gap-2 cursor-pointer">
            <Upload className="w-4 h-4" />
            {busy ? 'Uploading…' : 'Upload article'}
            <input
              type="file"
              className="hidden"
              accept=".pdf,.doc,.docx,.txt,.rtf,application/pdf"
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.currentTarget.value = '';
                if (file) void upload(file);
              }}
            />
          </label>
        </section>
      )}

      <section className="panel p-4">
        <h3 className="text-sm font-medium mb-3">Stored articles</h3>
        {files.length === 0 ? (
          <p className="text-gray-500 text-sm">No articles stored for this journal yet.</p>
        ) : (
          <div className="space-y-2">
            {files.map((row) => (
              <div
                key={row.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-gray-800 p-3"
              >
                <div className="min-w-0">
                  <p className="text-sm text-gray-100 font-medium break-all">{row.original_name}</p>
                  <p className="text-xs text-gray-500">
                    {formatSize(row.size_bytes)}
                    {row.created_at ? ` · ${formatWhen(row.created_at)}` : ''}
                  </p>
                </div>
                <button
                  className="btn-secondary inline-flex items-center gap-2"
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setDownloadId(row.id);
                    setPassword('');
                    setError('');
                  }}
                >
                  <Download className="w-4 h-4" />
                  Download
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {downloadId && (
        <div className="panel p-4 mt-4 max-w-lg">
          <p className="text-sm text-gray-200 mb-2">
            {admin
              ? 'Enter the admin password to download this stored article.'
              : 'Sign in as admin and enter the admin password to download this stored article.'}
          </p>
          <label className="text-sm text-gray-400">
            Admin password
            <input
              className="input-field mt-1"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <div className="flex flex-wrap gap-2 mt-3">
            <button className="btn-primary" type="button" disabled={busy || !password} onClick={() => void download()}>
              {busy ? 'Downloading…' : 'Download with password'}
            </button>
            <button
              className="btn-secondary"
              type="button"
              onClick={() => {
                setDownloadId(null);
                setPassword('');
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
