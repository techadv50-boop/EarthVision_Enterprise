import { useCallback, useEffect, useState } from 'react';
import { Library, Trash2, Upload } from 'lucide-react';
import {
  hostLibraryService,
  type HostLibrariesStatus,
} from '../../services/hostLibraryService';
import { getErrorMessage } from '../../services/api';

/**
 * Admin: install Host Python prerequisites into a persistent volume.
 * No Docker image rebuild — same idea as adding a package in a local venv.
 */
export function HostLibrariesSection() {
  const [status, setStatus] = useState<HostLibrariesStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pipName, setPipName] = useState('');

  const refresh = useCallback(async () => {
    const data = await hostLibraryService.list();
    setStatus(data);
  }, []);

  useEffect(() => {
    refresh().catch((err: unknown) =>
      setError(getErrorMessage(err) || 'Failed to load Host libraries'),
    );
  }, [refresh]);

  async function onUpload(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await hostLibraryService.uploadWheels(Array.from(files));
      if (res.ok === false) {
        setError(String(res.error || 'Upload failed'));
      } else {
        setMessage(
          `Installed: ${Array.isArray(res.installed) ? res.installed.join(', ') : 'ok'}. ` +
            String(res.restart_hint || ''),
        );
        await refresh();
      }
    } catch (err: unknown) {
      setError(getErrorMessage(err) || 'Upload failed');
    } finally {
      setBusy(false);
    }
  }

  async function onPipInstall() {
    const name = pipName.trim();
    if (!name) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await hostLibraryService.pipInstall(name);
      if (res.ok === false) {
        setError(String(res.error || 'pip install failed'));
      } else {
        setMessage(`Installed ${name}. ${String(res.restart_hint || '')}`);
        setPipName('');
        await refresh();
      }
    } catch (err: unknown) {
      setError(getErrorMessage(err) || 'pip install failed');
    } finally {
      setBusy(false);
    }
  }

  async function onUninstall(name: string) {
    if (!window.confirm(`Remove Host library "${name}" from the extras volume?`)) return;
    setBusy(true);
    setError(null);
    try {
      const res = await hostLibraryService.uninstall(name);
      if (res.ok === false) {
        setError(String(res.error || 'Uninstall failed'));
      } else {
        setMessage(`Removed ${name}`);
        await refresh();
      }
    } catch (err: unknown) {
      setError(getErrorMessage(err) || 'Uninstall failed');
    } finally {
      setBusy(false);
    }
  }

  const packages = Object.entries(status?.packages || {});

  return (
    <section
      className="mb-5 rounded-lg border border-[var(--line)] bg-[var(--bg)]/40 p-3"
      data-testid="admin-host-libraries"
    >
      <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <Library className="h-4 w-4 text-[var(--accent)]" />
        Host libraries (no rebuild)
      </h3>
      <p className="mb-3 text-[11px] text-[var(--muted)]">
        Upload a Python <code>.whl</code> here when a future plugin needs a package that is not
        already in the frozen Host stack. Libraries land on a persistent volume
        (<code>{status?.extras_dir || '/data/tool_packs/python_extras'}</code>) — like adding a
        package in Visual Studio / pip — without rebuilding frontend or backend images. Use{' '}
        <strong>Upload Plugin</strong> only for the tool pack itself.
      </p>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="ev-btn-primary inline-flex cursor-pointer items-center gap-1.5 px-3 py-1.5 text-xs">
          <Upload className="h-3.5 w-3.5" />
          Upload .whl
          <input
            type="file"
            accept=".whl,.tar.gz,.zip"
            multiple
            className="hidden"
            disabled={busy}
            onChange={(e) => void onUpload(e.target.files)}
          />
        </label>
        {status?.pip_from_index_enabled ? (
          <>
            <input
              className="ev-input max-w-[10rem] text-xs"
              placeholder="allowlisted package"
              value={pipName}
              disabled={busy}
              onChange={(e) => setPipName(e.target.value)}
            />
            <button
              type="button"
              className="ev-btn-ghost text-xs"
              disabled={busy || !pipName.trim()}
              onClick={() => void onPipInstall()}
            >
              pip install
            </button>
          </>
        ) : (
          <span className="text-[10px] text-[var(--muted)]">
            PyPI install off (upload .whl). Ops may set EV_HOST_LIBS_ALLOW_PIP=1.
          </span>
        )}
      </div>

      {message && (
        <p className="mb-2 text-[11px] text-emerald-800" role="status">
          {message}
        </p>
      )}
      {error && (
        <p className="mb-2 text-[11px] text-red-700" role="alert">
          {error}
        </p>
      )}

      <div className="max-h-40 overflow-y-auto rounded border border-[var(--line)] bg-white">
        {packages.length === 0 ? (
          <p className="p-2 text-[11px] text-[var(--muted)]">No extra Host libraries installed yet.</p>
        ) : (
          <ul className="divide-y divide-[var(--line)] text-[11px]">
            {packages.map(([name, meta]) => (
              <li key={name} className="flex items-center justify-between gap-2 px-2 py-1.5">
                <div className="min-w-0">
                  <div className="truncate font-semibold">{name}</div>
                  <div className="truncate text-[var(--muted)]">
                    {meta.source || '?'}
                    {meta.filename ? ` · ${meta.filename}` : ''}
                    {meta.installed_at ? ` · ${meta.installed_at}` : ''}
                  </div>
                </div>
                <button
                  type="button"
                  className="ev-btn-ghost p-1 text-red-700"
                  title="Remove"
                  disabled={busy}
                  onClick={() => void onUninstall(name)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
