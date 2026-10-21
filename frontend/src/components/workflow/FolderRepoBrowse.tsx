import { useEffect, useState } from 'react';
import { ArrowLeft, Download, FolderOpen, Loader2 } from 'lucide-react';
import {
  folderRepoService,
  type FolderFileEntry,
  type FolderRepoPublic,
} from '../../services/folderRepoService';
import { getErrorMessage } from '../../services/api';

interface Props {
  repo: FolderRepoPublic;
  onClose: () => void;
}

/**
 * Browse a relay folder repository: dates → files → download.
 * API key never leaves the SATEYE backend (Bearer is attached server-side).
 */
export function FolderRepoBrowse({ repo, onClose }: Props) {
  const [dates, setDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [files, setFiles] = useState<FolderFileEntry[]>([]);
  const [loadingDates, setLoadingDates] = useState(true);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoadingDates(true);
      setError(null);
      setSelectedDate(null);
      setFiles([]);
      try {
        const list = await folderRepoService.listDates(repo.id);
        if (!cancelled) setDates(list);
      } catch (err) {
        if (!cancelled) setError(getErrorMessage(err));
      } finally {
        if (!cancelled) setLoadingDates(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [repo.id]);

  const openDate = async (date: string) => {
    setSelectedDate(date);
    setLoadingFiles(true);
    setError(null);
    setFiles([]);
    try {
      setFiles(await folderRepoService.listFiles(repo.id, date));
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoadingFiles(false);
    }
  };

  const download = async (file: FolderFileEntry) => {
    if (!selectedDate) return;
    setDownloading(file.path);
    setError(null);
    try {
      await folderRepoService.downloadFile(repo.id, selectedDate, file.path);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="space-y-3" data-testid="folder-repo-browse">
      <div className="flex items-start justify-between gap-2">
        <div>
          <button
            type="button"
            className="mb-1 inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--accent)] hover:underline"
            onClick={onClose}
          >
            <ArrowLeft className="h-3 w-3" />
            Back
          </button>
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--ink)]">
            <FolderOpen className="h-4 w-4 text-[var(--accent)]" />
            {repo.label}
          </h3>
          <p className="mt-0.5 break-all font-mono text-[10px] text-[var(--muted)]">
            {repo.repository_url}
          </p>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      <div>
        <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
          1. Dates
        </div>
        {loadingDates ? (
          <div className="flex items-center gap-2 py-2 text-xs text-[var(--muted)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading dates…
          </div>
        ) : dates.length ? (
          <div className="grid max-h-40 grid-cols-2 gap-1.5 overflow-y-auto">
            {dates.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => void openDate(d)}
                className={`rounded-md border px-2 py-1.5 text-left text-xs font-medium ${
                  selectedDate === d
                    ? 'border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]'
                    : 'border-[var(--line)] hover:bg-[var(--bg)]'
                }`}
                data-testid={`folder-date-${d}`}
              >
                {d}
              </button>
            ))}
          </div>
        ) : (
          <p className="text-xs text-[var(--muted)]">No dates returned for this folder.</p>
        )}
      </div>

      {selectedDate && (
        <div>
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
            2. Files · {selectedDate}
          </div>
          {loadingFiles ? (
            <div className="flex items-center gap-2 py-2 text-xs text-[var(--muted)]">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading files…
            </div>
          ) : files.length ? (
            <ul className="max-h-52 space-y-1 overflow-y-auto">
              {files.map((f) => (
                <li
                  key={f.path}
                  className="flex items-center gap-2 rounded-md border border-[var(--line)] px-2 py-1.5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-medium">{f.name || f.path}</div>
                    {f.name && f.name !== f.path && (
                      <div className="truncate font-mono text-[10px] text-[var(--muted)]">
                        {f.path}
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[var(--accent)] px-2 py-1 text-[10px] font-semibold text-white disabled:opacity-50"
                    disabled={downloading === f.path}
                    onClick={() => void download(f)}
                    data-testid={`folder-download-${f.path}`}
                  >
                    {downloading === f.path ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Download className="h-3 w-3" />
                    )}
                    Download
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-[var(--muted)]">No files for this date.</p>
          )}
        </div>
      )}
    </div>
  );
}
