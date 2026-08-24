import { useEffect, useState } from 'react';
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

function CrawlProgress({ crawl }: { crawl: Record<string, unknown> }) {
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
        ? 'Scanning folders and subfolders for PDF files…'
        : found
          ? `Found ${found} PDF files. Loaded ${saved}, ${remaining} left.`
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
  const [files, setFiles] = useState<FileList | null>(null);
  const [archiveUrl, setArchiveUrl] = useState('');
  const [crawl, setCrawl] = useState<Record<string, unknown> | null>(null);
  const [msg, setMsg] = useState('');

  const load = async () => {
    const [{ data: j }, { data: vols }] = await Promise.all([
      citationApi.journals.get(id),
      citationApi.journals.volumes(id),
    ]);
    setJournal(j);
    setVolumes(vols);
    setArchiveUrl(j.archive_url || '');
  };

  useEffect(() => {
    void load();
  }, [id]);

  const upload = async () => {
    if (!files?.length) return;
    setMsg('Uploading…');
    await citationApi.journals.uploadPapers(id, Array.from(files));
    setMsg('Papers filed into the archive.');
    await load();
  };

  const startCrawl = async () => {
    setMsg('Starting crawler…');
    const { data } = await citationApi.journals.crawl(id, archiveUrl);
    setCrawl(data);
    const poll = async (jobId: number) => {
      const { data: job } = await citationApi.crawlJob(jobId);
      setCrawl(job);
      if (job.status === 'running' || job.status === 'queued') {
        setTimeout(() => void poll(jobId), 800);
      } else {
        setMsg(`Crawl ${job.status}`);
        await load();
      }
    };
    void poll(data.id);
  };

  return (
    <div>
      <p className="text-sm text-gray-500 mb-2">
        <Link to="/">Journals</Link> / {journal?.name}
      </p>
      <h2 className="text-2xl font-semibold mb-2">{journal?.name}</h2>
      <p className="text-gray-400 mb-6">Volumes and article totals. Missing volume numbers are flagged.</p>

      <div className="grid md:grid-cols-2 gap-4 mb-8">
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
          <h3 className="font-medium">2. Import from archive URL</h3>
          <input
            className="input-field"
            value={archiveUrl}
            onChange={(e) => setArchiveUrl(e.target.value)}
            placeholder="https://journal.50sea.com/index.php/IJIST/issue/archive"
          />
          <button className="btn-primary" type="button" onClick={() => void startCrawl()}>
            Crawl archive
          </button>
          {crawl && (
            <CrawlProgress crawl={crawl} />
          )}
        </div>
      </div>
      {msg && <p className="text-earth-400 text-sm mb-4">{msg}</p>}

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
