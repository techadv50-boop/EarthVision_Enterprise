import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { citationApi } from '@/services/api';

interface Suggestion {
  id: number;
  score: number;
  reason: string;
  house_citation?: string;
  status: string;
  article?: { title: string; volume?: number; issue_number?: number; page_start: number };
}

interface Paragraph {
  id: number;
  index: number;
  text: string;
  suggestions: Suggestion[];
}

export default function ManuscriptReviewPage() {
  const { manuscriptId } = useParams();
  const id = Number(manuscriptId);
  const [paras, setParas] = useState<Paragraph[]>([]);
  const [active, setActive] = useState<number | null>(null);
  const [title, setTitle] = useState('');
  const [exportText, setExportText] = useState('');

  const load = async () => {
    const { data } = await citationApi.manuscripts.get(id);
    setTitle(data.title || `Manuscript ${id}`);
    setParas(data.paragraphs || []);
    if (active == null && data.paragraphs?.length) setActive(data.paragraphs[0].id);
  };

  useEffect(() => {
    void load();
  }, [id]);

  const decide = async (sugId: number, status: string) => {
    await citationApi.patchSuggestion(sugId, status);
    await load();
  };

  const current = paras.find((p) => p.id === active);

  return (
    <div>
      <p className="text-sm text-gray-500 mb-2">
        <Link to="/manuscripts">Manuscripts</Link> / {title}
      </p>
      <div className="flex justify-between mb-4">
        <h2 className="text-2xl font-semibold">{title}</h2>
        <button
          className="btn-secondary"
          onClick={async () => {
            const { data } = await citationApi.manuscripts.export(id);
            setExportText(data.text);
          }}
        >
          Export accepted
        </button>
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        <div className="space-y-2 max-h-[70vh] overflow-auto">
          {paras.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setActive(p.id)}
              className={`panel p-3 text-left w-full ${p.suggestions.length ? 'border-earth-700' : ''} ${
                active === p.id ? 'ring-1 ring-earth-400' : ''
              }`}
            >
              <p className="text-xs text-gray-500 mb-1">
                ¶ {p.index + 1}
                {p.suggestions.length ? ` · ${p.suggestions.length} suggestions` : ''}
              </p>
              <p className="text-sm text-gray-200">{p.text.slice(0, 400)}</p>
            </button>
          ))}
        </div>
        <div className="space-y-3 max-h-[70vh] overflow-auto">
          {current?.suggestions.map((s) => (
            <div key={s.id} className="panel p-4">
              <p className="text-xs text-gray-500">
                score {s.score.toFixed(2)} · {s.status}
                {s.article
                  ? ` · Vol ${s.article.volume} Issue ${s.article.issue_number} p.${s.article.page_start}`
                  : ''}
              </p>
              <p className="font-medium mt-1">{s.article?.title}</p>
              <p className="text-sm text-gray-300 mt-2">{s.reason}</p>
              {s.house_citation && (
                <p className="text-xs text-earth-300 mt-2">{s.house_citation}</p>
              )}
              <div className="flex gap-2 mt-3">
                <button className="btn-primary" onClick={() => void decide(s.id, 'accepted')}>
                  Accept
                </button>
                <button className="btn-secondary" onClick={() => void decide(s.id, 'rejected')}>
                  Reject
                </button>
              </div>
            </div>
          ))}
          {current && current.suggestions.length === 0 && (
            <p className="text-gray-500">No archive matches for this paragraph.</p>
          )}
        </div>
      </div>
      {exportText && (
        <pre className="panel p-4 mt-4 text-xs whitespace-pre-wrap text-gray-300">{exportText}</pre>
      )}
    </div>
  );
}
