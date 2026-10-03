import { useEffect, useState } from 'react';
import { Globe } from 'lucide-react';
import { crawlerApi } from '@/services/api';

interface Progress {
  status: string;
  current_website: string;
  current_page: string;
  current_download: string;
  websites_completed: number;
  websites_remaining: number;
  websites_total: number;
  pages_crawled: number;
  documents_downloaded: number;
  emails_found: number;
  phone_numbers_found: number;
  elapsed_seconds: number;
  estimated_remaining_seconds: number | null;
  message: string;
}

interface Snapshot {
  busy: boolean;
  control_state: string;
  light_mode: boolean;
  output_folder: string;
  progress: Progress;
  resumable: { id: number; url: string; domain: string; status: string }[];
  log: string[];
  settings: Record<string, unknown>;
  version: string;
}

interface SiteRow {
  id: number;
  url: string;
  domain: string;
  status: string;
  email_count: number;
  phone_count: number;
  file_count: number;
  page_count: number;
}

interface SiteDetail {
  id: number;
  url: string;
  domain: string;
  status: string;
  emails: string[];
  phones: string[];
  pages: { url: string; status_code?: number | null }[];
  files: { url: string; file_path?: string | null; file_type?: string | null }[];
}

const emptyProgress: Progress = {
  status: 'Idle',
  current_website: '',
  current_page: '',
  current_download: '',
  websites_completed: 0,
  websites_remaining: 0,
  websites_total: 0,
  pages_crawled: 0,
  documents_downloaded: 0,
  emails_found: 0,
  phone_numbers_found: 0,
  elapsed_seconds: 0,
  estimated_remaining_seconds: null,
  message: '',
};

function fmtTime(seconds?: number | null) {
  if (seconds == null) return '—';
  const value = Math.max(0, Math.floor(seconds));
  const h = Math.floor(value / 3600);
  const m = Math.floor((value % 3600) / 60);
  const s = value % 60;
  if (h) return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export default function WebCrawlerPage() {
  const [urls, setUrls] = useState('');
  const [lightMode, setLightMode] = useState(true);
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [sites, setSites] = useState<SiteRow[]>([]);
  const [selected, setSelected] = useState<SiteDetail | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [settings, setSettings] = useState({
    crawl_depth: 10000,
    max_pages_per_site: 500000,
    page_workers: 16,
    worker_threads: 12,
    ignore_robots_txt: false,
    use_playwright_fallback: true,
  });

  const load = async () => {
    const [{ data }, sitesRes] = await Promise.all([
      crawlerApi.status(),
      crawlerApi.sites().catch(() => ({ data: [] as SiteRow[] })),
    ]);
    const next = data as Snapshot;
    setSnap(next);
    setLightMode(Boolean(next.light_mode));
    setSites((sitesRes.data || []) as SiteRow[]);
    if (next.settings) {
      setSettings((prev) => ({
        ...prev,
        crawl_depth: Number(next.settings.crawl_depth ?? prev.crawl_depth),
        max_pages_per_site: Number(next.settings.max_pages_per_site ?? prev.max_pages_per_site),
        page_workers: Number(next.settings.page_workers ?? prev.page_workers),
        worker_threads: Number(next.settings.worker_threads ?? prev.worker_threads),
        ignore_robots_txt: Boolean(next.settings.ignore_robots_txt),
        use_playwright_fallback: Boolean(next.settings.use_playwright_fallback),
      }));
    }
  };

  useEffect(() => {
    void load().catch(() => setError('Could not load the web crawler.'));
    const timer = window.setInterval(() => {
      void load().catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, []);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError('');
    try {
      await fn();
      await load();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'That crawler action failed.';
      setError(String(detail));
    } finally {
      setBusy(false);
    }
  };

  const progress = snap?.progress || emptyProgress;
  const running = Boolean(snap?.busy);

  return (
    <div>
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-2xl font-semibold inline-flex items-center gap-2">
            <Globe className="w-6 h-6 text-earth-400" />
            Web Crawler
            <span className="text-xs text-gray-500 font-normal">v{snap?.version || '1.4.2'}</span>
          </h2>
          <p className="text-gray-400 text-sm mt-1 max-w-3xl">
            Same engine as the offline WebCrawler Enterprise package: paste URLs, crawl each site,
            and collect emails and phone numbers. Light mode (default) reads every page without
            saving website files. Admin and user accounts both use this workspace.
          </p>
        </div>
        <button className="btn-secondary" type="button" onClick={() => setShowSettings((v) => !v)}>
          Settings
        </button>
      </div>
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      {(snap?.resumable?.length || 0) > 0 && !running && (
        <div className="panel p-4 mb-4">
          <p className="text-sm text-gray-200 mb-2">
            {snap!.resumable.length} website(s) were interrupted. Continue from the last saved page?
            Finished websites will not be crawled again. Nothing starts until you approve.
          </p>
          <ul className="text-xs text-gray-400 mb-3">
            {snap!.resumable.slice(0, 8).map((item) => (
              <li key={item.id}>• {item.url}</li>
            ))}
          </ul>
          <div className="flex gap-2">
            <button className="btn-primary" type="button" disabled={busy} onClick={() => void run(() => crawlerApi.resume())}>
              Yes, resume unfinished sites
            </button>
            <button className="btn-secondary" type="button" disabled={busy} onClick={() => void run(() => crawlerApi.clearSession())}>
              No, clear pending resume
            </button>
          </div>
        </div>
      )}

      {showSettings && (
        <form
          className="panel p-4 mb-4 grid gap-3 md:grid-cols-3"
          onSubmit={(e) => {
            e.preventDefault();
            void run(() => crawlerApi.saveSettings(settings));
          }}
        >
          <label className="text-sm text-gray-400">
            Crawl depth
            <input className="input-field mt-1" type="number" value={settings.crawl_depth} onChange={(e) => setSettings({ ...settings, crawl_depth: Number(e.target.value) })} />
          </label>
          <label className="text-sm text-gray-400">
            Max pages per website
            <input className="input-field mt-1" type="number" value={settings.max_pages_per_site} onChange={(e) => setSettings({ ...settings, max_pages_per_site: Number(e.target.value) })} />
          </label>
          <label className="text-sm text-gray-400">
            Page workers
            <input className="input-field mt-1" type="number" value={settings.page_workers} onChange={(e) => setSettings({ ...settings, page_workers: Number(e.target.value) })} />
          </label>
          <label className="text-sm text-gray-400 inline-flex items-center gap-2">
            <input type="checkbox" checked={settings.ignore_robots_txt} onChange={(e) => setSettings({ ...settings, ignore_robots_txt: e.target.checked })} />
            Ignore robots.txt
          </label>
          <label className="text-sm text-gray-400 inline-flex items-center gap-2">
            <input type="checkbox" checked={settings.use_playwright_fallback} onChange={(e) => setSettings({ ...settings, use_playwright_fallback: e.target.checked })} />
            Playwright fallback for JS pages
          </label>
          <div>
            <button className="btn-primary" type="submit" disabled={busy || running}>
              Save settings
            </button>
          </div>
        </form>
      )}

      <div className="grid gap-4 xl:grid-cols-5">
        <div className="xl:col-span-3 space-y-4">
          <div className="panel p-4">
            <label className="text-sm text-gray-400">
              Input URLs (one per line)
              <textarea
                className="input-field mt-1 min-h-[10rem] font-mono text-sm"
                placeholder={'https://www.harvard.edu\nhttps://www.mit.edu'}
                value={urls}
                onChange={(e) => setUrls(e.target.value)}
                readOnly={running}
              />
            </label>
            <label className="mt-3 text-sm text-gray-300 inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={lightMode}
                disabled={running}
                onChange={(e) => setLightMode(e.target.checked)}
              />
              Light mode — crawl ALL pages for emails & phones only (no file downloads, faster)
            </label>
            <div className="flex flex-wrap gap-2 mt-4">
              <button className="btn-primary" type="button" disabled={busy || running} onClick={() => void run(() => crawlerApi.start(urls, lightMode))}>
                Start
              </button>
              <button className="btn-secondary" type="button" disabled={busy || !running} onClick={() => void run(() => crawlerApi.pause())}>
                Pause
              </button>
              <button className="btn-secondary" type="button" disabled={busy} onClick={() => void run(() => crawlerApi.resume())}>
                Resume
              </button>
              <button className="btn-secondary" type="button" disabled={busy || !running} onClick={() => void run(() => crawlerApi.nextSite())}>
                Next Site
              </button>
              <button className="btn-secondary" type="button" disabled={busy || !running} onClick={() => void run(() => crawlerApi.stop())}>
                Stop
              </button>
              <button className="btn-secondary" type="button" disabled={busy || running} onClick={() => setUrls('')}>
                Clear URLs
              </button>
            </div>
            <label className="block text-sm text-gray-400 mt-4">
              Scan a local folder of PDF / Word / HTML / .eml (zip)
              <input
                className="mt-1 block text-sm"
                type="file"
                accept=".zip"
                disabled={busy || running}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.currentTarget.value = '';
                  if (file) void run(() => crawlerApi.scanFolder(file));
                }}
              />
            </label>
          </div>
          <div className="panel p-4">
            <h3 className="text-sm font-medium mb-2">Activity log</h3>
            <pre className="text-xs text-gray-400 whitespace-pre-wrap max-h-64 overflow-auto min-h-[8rem]">
              {(snap?.log || []).join('\n') || 'Ready. Paste URLs and click Start. Nothing crawls until you approve.'}
            </pre>
          </div>
        </div>

        <div className="xl:col-span-2 space-y-4">
          <div className="panel p-4">
            <h3 className="text-sm font-medium mb-3">Progress</h3>
            <dl className="grid grid-cols-1 gap-2 text-sm">
              {[
                ['Status', progress.status],
                ['Current website', progress.current_website || '—'],
                ['Current page', progress.current_page || '—'],
                ['Current download', progress.current_download || '—'],
                ['Websites completed', String(progress.websites_completed)],
                ['Websites remaining', String(progress.websites_remaining)],
                ['Pages crawled', String(progress.pages_crawled)],
                ['Documents downloaded', String(progress.documents_downloaded)],
                ['Emails found', String(progress.emails_found)],
                ['Phone numbers found', String(progress.phone_numbers_found)],
                ['Elapsed', fmtTime(progress.elapsed_seconds)],
                ['Estimated remaining', fmtTime(progress.estimated_remaining_seconds)],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-3">
                  <dt className="text-gray-500">{label}</dt>
                  <dd className="text-gray-200 text-right break-all">{value}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="panel p-4">
            <h3 className="text-sm font-medium mb-2">Browser — crawled websites</h3>
            <p className="text-xs text-gray-500 mb-3">
              Open a site to see which URLs were visited and the emails, phones, and files that were
              downloaded.
            </p>
            {sites.length === 0 ? (
              <p className="text-sm text-gray-500">No websites crawled yet.</p>
            ) : (
              <ul className="space-y-1 max-h-48 overflow-auto">
                {sites.map((site) => (
                  <li key={site.id}>
                    <button
                      type="button"
                      className={`w-full text-left text-sm px-2 py-1 rounded ${
                        selected?.id === site.id ? 'bg-earth-900/40 text-earth-300' : 'hover:bg-gray-800'
                      }`}
                      onClick={() => {
                        void crawlerApi
                          .site(site.id)
                          .then(({ data }) => setSelected(data as SiteDetail))
                          .catch(() => setError('Could not open that crawled site.'));
                      }}
                    >
                      <span className="font-medium">{site.domain || site.url}</span>
                      <span className="text-xs text-gray-500 ml-2">
                        {site.status} · {site.email_count} emails · {site.phone_count} phones · {site.file_count} files
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {selected && (
              <div className="mt-4 border-t border-gray-800 pt-3 space-y-3">
                <div className="flex items-center justify-between gap-2">
                  <h4 className="font-medium">{selected.domain}</h4>
                  <a className="text-earth-400 text-sm" href={selected.url} target="_blank" rel="noreferrer">
                    Open website
                  </a>
                </div>
                <p className="text-xs text-gray-500">{selected.status}</p>
                <div>
                  <p className="text-xs text-gray-500 mb-1">Emails ({selected.emails.length})</p>
                  <pre className="text-xs text-gray-300 whitespace-pre-wrap max-h-32 overflow-auto">
                    {selected.emails.join('\n') || '—'}
                  </pre>
                </div>
                <div>
                  <p className="text-xs text-gray-500 mb-1">Phone numbers ({selected.phones.length})</p>
                  <pre className="text-xs text-gray-300 whitespace-pre-wrap max-h-32 overflow-auto">
                    {selected.phones.join('\n') || '—'}
                  </pre>
                </div>
                <div>
                  <p className="text-xs text-gray-500 mb-1">Downloaded files ({selected.files.length})</p>
                  <ul className="text-xs text-gray-300 max-h-28 overflow-auto">
                    {selected.files.length === 0 && <li>—</li>}
                    {selected.files.map((file) => (
                      <li key={file.url} className="truncate">
                        {file.file_type || 'file'} · {file.url}
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <p className="text-xs text-gray-500 mb-1">Pages visited ({selected.pages.length})</p>
                  <ul className="text-xs text-gray-400 max-h-28 overflow-auto">
                    {selected.pages.length === 0 && <li>—</li>}
                    {selected.pages.map((page) => (
                      <li key={page.url} className="truncate">
                        {page.status_code || '—'} · {page.url}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
