import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { citationApi } from '@/services/api';

interface Volume {
  volume: number;
  year_start?: number;
  year_end?: number;
  article_count: number;
  issue_count: number;
  missing: boolean;
}

type InventoryRow = {
  url: string;
  title?: string;
  volume?: number | null;
  issue_number?: number | null;
  year?: number | null;
  article_count?: number;
  downloaded?: boolean;
};

type LocalIssue = {
  id: number;
  volume: number;
  issue_number: number;
  year?: number;
  month?: string;
  article_count: number;
  cited_count: number;
  uncited_count: number;
  scholar_total: number;
  crossref_total: number;
  citations_synced?: boolean;
};

type CrawlJob = Record<string, unknown> & {
  id?: number;
  status?: string;
  phase?: string;
  message?: string;
  inventory?: InventoryRow[];
};

function issueLabel(row: { volume?: number | null; issue_number?: number | null; year?: number | null; title?: string; url?: string; month?: string }) {
  if (row.volume && row.issue_number) {
    const when = row.month || row.year ? ` (${[row.month, row.year].filter(Boolean).join(' ')})` : '';
    return `Vol. ${row.volume} No. ${row.issue_number}${when}`;
  }
  return row.title || row.url || 'Issue';
}

function isActiveStatus(status?: string) {
  return status === 'running' || status === 'queued';
}

function CrawlProgress({ crawl }: { crawl: CrawlJob }) {
  const found = Number(crawl.articles_found || 0);
  const saved = Number(crawl.articles_saved || 0);
  const skipped = Number(crawl.articles_skipped || 0);
  const remaining = Math.max(0, found - saved - skipped);
  const processed = saved + skipped;
  const phase = String(crawl.phase || crawl.status || '');
  const scanning = phase === 'scanning' || (found === 0 && (phase === 'running' || phase === 'queued'));
  const percent = found > 0 ? Math.min(100, Math.round((processed / found) * 100)) : scanning ? 8 : 0;
  const message = String(
    crawl.message ||
      (scanning
        ? 'Listing issues and article counts…'
        : found
          ? `Found ${found} PDFs. Loaded ${saved}, ${remaining} left.`
          : String(crawl.status))
  );

  return (
    <div className="space-y-2 text-sm">
      <p className="text-earth-400">{message}</p>
      <div className="h-2 rounded bg-gray-800 overflow-hidden">
        <div className="h-full bg-earth-500 transition-all" style={{ width: `${percent}%` }} />
      </div>
      <p className="text-xs text-gray-400">
        {scanning
          ? `Searching… ${Number(crawl.pages_crawled || 0)} pages opened`
          : `PDFs found: ${found} · loaded ${saved} · left ${remaining}` +
            (skipped ? ` · skipped ${skipped}` : '')}
      </p>
    </div>
  );
}

export default function JournalVolumesPage() {
  const { journalId } = useParams();
  const id = Number(journalId);
  const [journal, setJournal] = useState<{ name: string; archive_url?: string } | null>(null);
  const [volumes, setVolumes] = useState<Volume[]>([]);
  const [localIssues, setLocalIssues] = useState<LocalIssue[]>([]);
  const [files, setFiles] = useState<FileList | null>(null);
  const [archiveUrl, setArchiveUrl] = useState('');
  const [crawl, setCrawl] = useState<CrawlJob | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [msg, setMsg] = useState('');
  const [syncing, setSyncing] = useState(false);

  const inventory = useMemo(
    () => (Array.isArray(crawl?.inventory) ? (crawl?.inventory as InventoryRow[]) : []),
    [crawl]
  );
  const downloading = isActiveStatus(crawl?.status) && String(crawl?.phase || '') === 'downloading';
  const scanning = isActiveStatus(crawl?.status) && !downloading;

  const localByKey = useMemo(() => {
    const map = new Map<string, LocalIssue>();
    for (const iss of localIssues) {
      map.set(`${iss.volume}-${iss.issue_number}`, iss);
    }
    return map;
  }, [localIssues]);

  const issueRows = useMemo(() => {
    const rows: Array<{
      key: string;
      url?: string;
      volume?: number | null;
      issue_number?: number | null;
      year?: number | null;
      month?: string;
      title?: string;
      article_count: number;
      on_file_count?: number;
      scholar_total: number;
      crossref_total: number;
      cited_count: number;
      downloaded: boolean;
      localId?: number;
    }> = [];
    const seen = new Set<string>();
    for (const row of inventory) {
      const key = row.volume && row.issue_number ? `${row.volume}-${row.issue_number}` : row.url;
      const local = row.volume && row.issue_number ? localByKey.get(`${row.volume}-${row.issue_number}`) : undefined;
      rows.push({
        key,
        url: row.url,
        volume: row.volume,
        issue_number: row.issue_number,
        year: local?.year ?? row.year,
        month: local?.month,
        title: row.title,
        article_count: Number(row.article_count || local?.article_count || 0),
        on_file_count: local?.article_count || 0,
        scholar_total: local?.scholar_total || 0,
        crossref_total: local?.crossref_total || 0,
        cited_count: local?.cited_count || 0,
        downloaded: Boolean(local || row.downloaded),
        localId: local?.id,
      });
      seen.add(key);
    }
    for (const iss of localIssues) {
      const key = `${iss.volume}-${iss.issue_number}`;
      if (seen.has(key)) continue;
      rows.push({
        key,
        volume: iss.volume,
        issue_number: iss.issue_number,
        year: iss.year,
        month: iss.month,
        article_count: iss.article_count,
        scholar_total: iss.scholar_total,
        crossref_total: iss.crossref_total,
        cited_count: iss.cited_count,
        downloaded: true,
        localId: iss.id,
      });
    }
    return rows;
  }, [inventory, localIssues, localByKey]);

  const load = async (): Promise<LocalIssue[]> => {
    const [{ data: j }, { data: vols }, issuesRes] = await Promise.all([
      citationApi.journals.get(id),
      citationApi.journals.volumes(id),
      citationApi.journals.allIssues(id).catch(() => ({ data: [] as LocalIssue[] })),
    ]);
    setJournal(j);
    setVolumes(vols);
    const issues: LocalIssue[] = issuesRes.data || [];
    setLocalIssues(issues);
    setArchiveUrl(j.archive_url || '');
    try {
      const { data: job } = await citationApi.journals.latestCrawl(id);
      if (job?.inventory?.length) {
        setCrawl(job);
        const next: Record<string, boolean> = {};
        for (const row of job.inventory as InventoryRow[]) {
          next[row.url] = false;
        }
        setSelected(next);
      }
    } catch {
      /* no prior scan */
    }
    return issues;
  };

  const refreshCitations = async () => {
    if (syncing) return;
    setSyncing(true);
    setMsg('Looking up Crossref and Google Scholar cited-by counts…');
    try {
      await citationApi.journals.syncCitations(id);
      await load();
      setMsg('Citation counts updated from Crossref and Google Scholar.');
    } catch {
      setMsg('Could not refresh citation counts. Try again in a moment.');
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    void (async () => {
      const issues = await load();
      const needsSync = issues.some((iss) => iss.article_count > 0 && !iss.citations_synced);
      if (needsSync) {
        await refreshCitations();
      }
    })();
  }, [id]);

  const pollJob = async (jobId: number) => {
    const { data: job } = await citationApi.crawlJob(jobId);
    setCrawl(job);
    if (isActiveStatus(job.status)) {
      setTimeout(() => void pollJob(jobId), 600);
      return;
    }
    if (job.status === 'awaiting_selection' || Array.isArray(job.inventory)) {
      const next: Record<string, boolean> = {};
      for (const row of (job.inventory || []) as InventoryRow[]) {
        next[row.url] = false;
      }
      setSelected(next);
    }
    if (job.status === 'awaiting_selection') {
      setMsg('Choose which issues to download. Unchecked issues are left on the site.');
      await load();
      return;
    }
    setMsg(job.message || `Crawl ${job.status}`);
    await load();
  };

  const upload = async () => {
    if (!files?.length) return;
    setMsg('Uploading…');
    await citationApi.journals.uploadPapers(id, Array.from(files));
    setMsg('Papers filed into the archive.');
    const issues = await load();
    if (issues.some((iss) => iss.article_count > 0 && !iss.citations_synced)) {
      await refreshCitations();
    }
  };

  const startCrawl = async () => {
    setMsg('Scanning issues…');
    setSelected({});
    const { data } = await citationApi.journals.crawl(id, archiveUrl);
    setCrawl(data);
    void pollJob(data.id);
  };

  const startDownload = async () => {
    if (!crawl?.id) return;
    const issueUrls = Object.entries(selected)
      .filter(([, on]) => on)
      .map(([url]) => url);
    if (!issueUrls.length) {
      setMsg('Select at least one issue to download, or leave them all unchecked.');
      return;
    }
    setMsg('Downloading selected issue PDFs…');
    const { data } = await citationApi.downloadCrawl(crawl.id, issueUrls);
    setCrawl(data);
    void pollJob(data.id);
  };

  const toggleAll = (value: boolean) => {
    const next: Record<string, boolean> = {};
    for (const row of inventory) {
      next[row.url] = row.downloaded ? false : value;
    }
    setSelected(next);
  };

  const selectedCount = inventory.filter((row) => selected[row.url]).length;
  const selectedArticles = inventory
    .filter((row) => selected[row.url])
    .reduce((sum, row) => sum + Number(row.article_count || 0), 0);

  return (
    <div>
      <p className="text-sm text-gray-500 mb-2">
        <Link to="/">Journals</Link> / {journal?.name}
      </p>
      <h2 className="text-2xl font-semibold mb-2">{journal?.name}</h2>
      <p className="text-gray-400 mb-6">Volumes and article totals. Missing volume numbers are flagged.</p>

      <div className="grid md:grid-cols-2 gap-4 mb-4">
        <div className="panel p-4 space-y-3">
          <h3 className="font-medium">1. Upload PDFs</h3>
          <input
            type="file"
            accept="application/pdf"
            multiple
            onChange={(e) => setFiles(e.target.files)}
          />
          <button className="btn-primary" type="button" onClick={() => void upload()}>
            Upload and file by volume/issue
          </button>
        </div>
        <div className="panel p-4 space-y-3">
          <h3 className="font-medium">2. Scan archive issues</h3>
          <p className="text-xs text-gray-400">
            Lists every issue and how many articles it contains. Article pages are opened when the
            PDF is not on the issue table of contents. PDFs are not downloaded until you choose which
            issues to fetch. Citation counts come from the DOI (Crossref) and Google Scholar.
          </p>
          <input
            className="input-field"
            value={archiveUrl}
            onChange={(e) => setArchiveUrl(e.target.value)}
            placeholder="https://journal.50sea.com/index.php/IJIST/issue/archive"
          />
          <div className="flex gap-2 flex-wrap">
            <button
              className="btn-primary"
              type="button"
              disabled={scanning || downloading || !archiveUrl}
              onClick={() => void startCrawl()}
            >
              Scan issues
            </button>
            {(scanning || downloading) && crawl?.id ? (
              <button
                className="btn-secondary"
                type="button"
                onClick={() => void citationApi.cancelCrawl(Number(crawl.id))}
              >
                Cancel
              </button>
            ) : null}
            {localIssues.length > 0 && (
              <button className="btn-secondary" type="button" disabled={syncing} onClick={() => void refreshCitations()}>
                {syncing ? 'Refreshing citations…' : 'Refresh citation counts'}
              </button>
            )}
          </div>
          {crawl && (scanning || downloading) && <CrawlProgress crawl={crawl} />}
        </div>
      </div>
      {msg && <p className="text-earth-400 text-sm mb-4">{msg}</p>}

      {issueRows.length > 0 && (
        <div className="panel p-4 mb-8 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="font-medium">2. Issues</h3>
              <p className="text-sm text-gray-400">
                {issueRows.length} issues ·{' '}
                {issueRows.reduce((n, row) => n + Number(row.article_count || 0), 0)} articles.
                Tick remote issues to download; leave the rest on the site.
              </p>
            </div>
            {inventory.length > 0 && (
              <div className="flex gap-2">
                <button className="btn-secondary" type="button" onClick={() => toggleAll(true)}>
                  Select all
                </button>
                <button className="btn-secondary" type="button" onClick={() => toggleAll(false)}>
                  Leave all
                </button>
              </div>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-gray-400 border-b border-gray-800">
                <tr>
                  <th className="py-2 pr-3 w-10">Get</th>
                  <th className="py-2 pr-3">Issue</th>
                  <th className="py-2 pr-3 text-right">Articles</th>
                  <th className="py-2 pr-3 text-right">Scholar</th>
                  <th className="py-2 pr-3 text-right">Crossref</th>
                  <th className="py-2 pl-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {issueRows.map((row) => (
                  <tr key={row.key} className="border-b border-gray-800/80">
                    <td className="py-2 pr-3">
                      {row.url ? (
                        <input
                          type="checkbox"
                          checked={Boolean(selected[row.url])}
                          disabled={Boolean(row.downloaded) && !inventory.find((i) => i.url === row.url)}
                          onChange={(e) =>
                            setSelected((prev) => ({ ...prev, [row.url!]: e.target.checked }))
                          }
                        />
                      ) : (
                        <span className="text-gray-600">—</span>
                      )}
                    </td>
                    <td className="py-2 pr-3">
                      {row.localId && row.volume ? (
                        <Link
                          to={`/journals/${id}/volumes/${row.volume}/issues/${row.issue_number}`}
                          className="hover:text-earth-400"
                        >
                          {issueLabel(row)}
                        </Link>
                      ) : (
                        <div>{issueLabel(row)}</div>
                      )}
                      {row.title && row.volume ? (
                        <div className="text-xs text-gray-500 truncate max-w-xl">{row.title}</div>
                      ) : null}
                    </td>
                    <td className="py-2 pr-3 text-right font-medium">
                      {Number(row.article_count || 0)}
                      {row.on_file_count && row.on_file_count !== row.article_count ? (
                        <div className="text-xs text-gray-500 font-normal">{row.on_file_count} on file</div>
                      ) : null}
                    </td>
                    <td className="py-2 pr-3 text-right">{row.scholar_total}</td>
                    <td className="py-2 pr-3 text-right">{row.crossref_total}</td>
                    <td className="py-2 pl-3 text-xs text-gray-400">
                      {row.downloaded
                        ? row.cited_count
                          ? `On file · ${row.cited_count} cited`
                          : 'On file'
                        : selected[row.url || '']
                          ? 'Will download'
                          : 'Leave'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {inventory.length > 0 && (
            <button className="btn-primary" type="button" onClick={() => void startDownload()}>
              Download {selectedCount} selected issue{selectedCount === 1 ? '' : 's'}
              {selectedArticles ? ` (${selectedArticles} articles)` : ''}
            </button>
          )}
        </div>
      )}

      <div className="space-y-2">
        {volumes.map((v) =>
          v.missing ? (
            <div key={v.volume} className="panel p-4 border-amber-800 text-amber-300">
              Volume {v.volume} missing
            </div>
          ) : (
            <Link
              key={v.volume}
              to={`/journals/${id}/volumes/${v.volume}`}
              className="panel p-4 flex justify-between hover:border-earth-500 block"
            >
              <span className="font-medium">Volume {v.volume}</span>
              <span className="text-gray-400">
                {v.article_count} articles · {v.issue_count} issues
                {v.year_start ? ` · ${v.year_start}` : ''}
              </span>
            </Link>
          )
        )}
      </div>
    </div>
  );
}
