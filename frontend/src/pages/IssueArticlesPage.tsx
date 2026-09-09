import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { citationApi } from '@/services/api';

interface Article {
  id: number;
  title: string;
  authors: string[];
  page_start: number;
  page_end?: number;
  scholar_citation_count: number;
  crossref_citation_count: number;
  doi?: string;
  scholar_url?: string;
  crossref_work_url?: string;
  citation_sync_status?: string;
  citation_synced_at?: string;
  citing_works?: CitingWork[];
}

interface CitingWork {
  source?: string;
  title?: string;
  authors?: string;
  year?: number;
  venue?: string;
  doi?: string;
  url?: string;
}

function sourceParts(source?: string) {
  return (source || '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
}

function displaySource(source?: string): 'crossref' | 'scholar' | null {
  const parts = sourceParts(source);
  if (parts.includes('scholar')) return 'scholar';
  if (parts.includes('crossref')) return 'crossref';
  return null;
}

function normTitle(title?: string) {
  return (title || '')
    .toLowerCase()
    .replace(/<[^>]+>/g, ' ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

function doiQuality(doi?: string) {
  const value = (doi || '').toLowerCase();
  const preprint = /10\.21203\/|\/rs\.3\.rs-/.test(value) ? 1 : 0;
  const doubled = /^(10\.\d+)\/\1\//.test(value) ? 1 : 0;
  return preprint + doubled;
}

function preferWork(existing: CitingWork, incoming: CitingWork) {
  const better = doiQuality(incoming.doi) < doiQuality(existing.doi) ? incoming : existing;
  const other = better === incoming ? existing : incoming;
  return {
    ...other,
    ...Object.fromEntries(Object.entries(better).filter(([, value]) => value !== undefined && value !== '')),
  } as CitingWork;
}

function uniqueWorks(works: CitingWork[]) {
  const byTitle = new Map<string, CitingWork>();
  const untitled: CitingWork[] = [];
  const seenDoi = new Set<string>();
  for (const work of works) {
    const doi = (work.doi || '').trim().toLowerCase();
    if (doi) {
      if (seenDoi.has(doi)) continue;
      seenDoi.add(doi);
    }
    const title = normTitle(work.title);
    if (!title) {
      untitled.push(work);
      continue;
    }
    const existing = byTitle.get(title);
    byTitle.set(title, existing ? preferWork(existing, work) : work);
  }
  return [...byTitle.values(), ...untitled];
}

function worksForSource(works: CitingWork[], source: 'crossref' | 'scholar') {
  return uniqueWorks(works.filter((work) => displaySource(work.source) === source));
}

function needsCitingListRefresh(articles: Article[]) {
  return articles.some((article) => {
    const works = article.citing_works || [];
    if (works.some((work) => sourceParts(work.source).includes('openalex'))) return true;
    const hasScholarList = works.some((work) => displaySource(work.source) === 'scholar');
    if ((article.scholar_citation_count || 0) > 0 && article.scholar_url && !hasScholarList) return true;
    const hasCrossrefList = works.some((work) => displaySource(work.source) === 'crossref');
    if ((article.crossref_citation_count || 0) > 0 && !hasCrossrefList) return true;
    return false;
  });
}

interface Payload {
  issue: {
    id: number;
    article_count: number;
    cited_count: number;
    uncited_count: number;
    scholar_total: number;
    crossref_total: number;
  };
  articles: Article[];
  coverage: { gaps: { page_start: number; page_end: number }[]; overlaps: unknown[] };
}

export default function IssueArticlesPage() {
  const { journalId, volume, issueNumber } = useParams();
  const id = Number(journalId);
  const vol = Number(volume);
  const iss = Number(issueNumber);
  const [data, setData] = useState<Payload | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [doiDraft, setDoiDraft] = useState<Record<number, string>>({});

  const load = async () => {
    const { data: payload } = await citationApi.journals.articles(id, vol, iss);
    setData(payload);
    return payload as Payload;
  };

  useEffect(() => {
    void (async () => {
      const payload = await load();
      if (!payload.issue.id) return;
      const marker = `citing-works-v2-${payload.issue.id}`;
      const needCounts = (payload.articles || []).some((a) => !a.citation_synced_at);
      const needLists =
        needsCitingListRefresh(payload.articles || []) && !sessionStorage.getItem(marker);
      if (!needCounts && !needLists) return;
      sessionStorage.setItem(marker, '1');
      setMsg('Fetching Cite by Crossref and Cite by Google Scholar lists…');
      await citationApi.syncIssue(payload.issue.id);
      await load();
      setMsg('');
    })();
  }, [id, vol, iss]);

  const sync = async () => {
    if (!data?.issue.id) return;
    setBusy(true);
    await citationApi.syncIssue(data.issue.id);
    await load();
    setBusy(false);
  };

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setMsg('Uploading…');
    await citationApi.journals.uploadPapers(id, Array.from(files));
    setMsg('Papers filed into this issue when headers match.');
    await load();
  };

  const saveDoi = async (articleId: number) => {
    const doi = doiDraft[articleId];
    if (!doi) return;
    await citationApi.patchArticle(articleId, { doi });
    await citationApi.syncArticle(articleId);
    await load();
  };

  if (!data) return <p className="text-gray-400">Loading…</p>;

  return (
    <div>
      <p className="text-sm text-gray-500 mb-2">
        <Link to="/">Journals</Link> / <Link to={`/journals/${id}`}>Journal</Link> /{' '}
        <Link to={`/journals/${id}/volumes/${vol}`}>Vol. {vol}</Link> / Issue {iss}
      </p>
      <div className="flex flex-wrap justify-between items-center gap-3 mb-4">
        <div>
          <h2 className="text-2xl font-semibold">Issue {iss}</h2>
          <p className="text-gray-400 text-sm">
            {data.issue.article_count} articles · {data.issue.cited_count} cited (Scholar{' '}
            {data.issue.scholar_total} / Crossref {data.issue.crossref_total}) ·{' '}
            {data.issue.uncited_count} not cited
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <label className="btn-secondary cursor-pointer">
            Upload PDFs
            <input
              type="file"
              accept="application/pdf"
              multiple
              className="hidden"
              onChange={(e) => void upload(e.target.files)}
            />
          </label>
          <button className="btn-primary" disabled={busy} onClick={() => void sync()}>
            Refresh citations
          </button>
        </div>
      </div>
      {msg && <p className="text-earth-400 text-sm mb-3">{msg}</p>}

      {data.coverage.gaps.map((g) => (
        <div key={`${g.page_start}-${g.page_end}`} className="panel p-3 mb-2 border-amber-800">
          <span className="text-amber-300">
            Missing pages {g.page_start}–{g.page_end}
          </span>
          <span className="text-gray-500 text-sm"> — upload a PDF above to fill this gap.</span>
        </div>
      ))}

      <div className="space-y-2 mt-4">
        {data.articles.map((a) => (
          <div key={a.id} className="panel p-4">
            <p className="font-medium">{a.title}</p>
            <p className="text-sm text-gray-400">
              {(a.authors || []).join(', ')} · pp {a.page_start}
              {a.page_end ? `–${a.page_end}` : ''}
            </p>
            <p className="text-sm mt-2">
              Google Scholar <strong>{a.scholar_citation_count}</strong> · Crossref{' '}
              <strong>{a.crossref_citation_count}</strong>
              {a.citation_sync_status ? ` · ${a.citation_sync_status}` : ''}
              {a.citation_synced_at
                ? ` · last synced ${new Date(a.citation_synced_at).toLocaleString()}`
                : ''}
            </p>
            <div className="flex flex-wrap gap-2 mt-3">
              <input
                className="input-field max-w-xs"
                placeholder={a.doi || 'DOI'}
                value={doiDraft[a.id] ?? a.doi ?? ''}
                onChange={(e) => setDoiDraft((d) => ({ ...d, [a.id]: e.target.value }))}
              />
              <button className="btn-secondary" type="button" onClick={() => void saveDoi(a.id)}>
                Save DOI & sync
              </button>
              <button
                className="btn-secondary"
                type="button"
                onClick={async () => {
                  await citationApi.syncArticle(a.id);
                  await load();
                }}
              >
                Sync this paper
              </button>
            </div>
            {(a.crossref_work_url || a.doi) && (
              <a
                className="text-xs text-earth-400 mt-2 inline-block mr-3"
                href={a.crossref_work_url || `https://doi.org/${a.doi}`}
                target="_blank"
                rel="noreferrer"
              >
                Crossref record
              </a>
            )}
            {a.scholar_url && (
              <a className="text-xs text-earth-400 mt-2 inline-block mr-3" href={a.scholar_url} target="_blank" rel="noreferrer">
                {a.scholar_url.includes("cites=") ? "Google Scholar cited-by list" : "Google Scholar record"}
              </a>
            )}
            <CitingWorksList article={a} />
          </div>
        ))}
      </div>
    </div>
  );
}

function CitingWorkItems({
  source,
  works,
}: {
  source: 'crossref' | 'scholar';
  works: CitingWork[];
}) {
  if (!works.length) {
    return null;
  }
  return (
    <ul className="space-y-2">
      {works.map((work, idx) => {
        const href = work.url || (work.doi ? `https://doi.org/${work.doi}` : undefined);
        return (
          <li key={`${source}-${work.doi || work.url || work.title || idx}`} className="text-sm text-gray-300">
            <span className="text-gray-500 mr-2">{idx + 1}.</span>
            {href ? (
              <a className="text-earth-400 hover:underline" href={href} target="_blank" rel="noreferrer">
                {work.title}
              </a>
            ) : (
              <span>{work.title}</span>
            )}
            <div className="text-xs text-gray-500 ml-5">
              {[work.authors, work.year, work.venue].filter(Boolean).join(' · ')}
              {work.doi ? ` · DOI ${work.doi}` : ''}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function CitingWorksList({ article }: { article: Article }) {
  const works = article.citing_works || [];
  const crossrefWorks = worksForSource(works, 'crossref');
  const scholarWorks = worksForSource(works, 'scholar');
  const crossrefCount = article.crossref_citation_count || 0;
  const scholarCount = article.scholar_citation_count || 0;

  return (
    <div className="mt-4 space-y-4">
      <div className="space-y-1">
        <p className="text-sm font-medium">
          Cite by Crossref{' '}
          <span className="text-gray-400 font-normal">
            ({crossrefWorks.length}
            {crossrefCount > 0 && crossrefWorks.length !== crossrefCount ? ` of ${crossrefCount}` : ''})
          </span>
        </p>
        <p className="text-sm font-medium">
          Cite by Google Scholar{' '}
          <span className="text-gray-400 font-normal">
            ({scholarWorks.length}
            {scholarCount > 0 && scholarWorks.length !== scholarCount ? ` of ${scholarCount}` : ''})
          </span>
        </p>
        {scholarCount === 0 && scholarWorks.length === 0 && (
          <p className="text-xs text-gray-500">No Google Scholar citing articles for this paper.</p>
        )}
        {scholarCount > 0 && scholarWorks.length === 0 && (
          <p className="text-xs text-gray-500">
            Google Scholar reports {scholarCount} citation{scholarCount === 1 ? '' : 's'}
            {article.scholar_url ? ', but the cited-by list could not be loaded here. Open the Scholar link above.' : '.'}
          </p>
        )}
      </div>
      <section>
        {crossrefCount > 0 && crossrefWorks.length === 0 && (
          <p className="text-xs text-gray-500 mb-2">
            Crossref reports {crossrefCount} citation{crossrefCount === 1 ? '' : 's'}, but no citing-article
            records were returned for this DOI. Use Refresh citations to look them up again.
          </p>
        )}
        {crossrefCount === 0 && crossrefWorks.length === 0 && (
          <p className="text-xs text-gray-500">No Crossref citing articles for this paper.</p>
        )}
        <CitingWorkItems source="crossref" works={crossrefWorks} />
      </section>
      {scholarWorks.length > 0 && (
        <section>
          <CitingWorkItems source="scholar" works={scholarWorks} />
        </section>
      )}
    </div>
  );
}
