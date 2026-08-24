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
  citation_sync_status?: string;
  citation_synced_at?: string;
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
      const need = (payload.articles || []).some((a) => !a.citation_synced_at);
      if (!need || !payload.issue.id) return;
      setMsg('Fetching Crossref and Google Scholar cited-by counts…');
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
            {a.scholar_url && (
              <a className="text-xs text-earth-400 mt-2 inline-block" href={a.scholar_url}>
                Scholar record
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
