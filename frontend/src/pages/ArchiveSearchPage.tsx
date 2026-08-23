import { useState } from 'react';
import { citationApi } from '@/services/api';

interface Hit {
  id: number;
  title: string;
  volume?: number;
  issue_number?: number;
  page_start: number;
  snippet?: string;
  full_text?: string;
}

export default function ArchiveSearchPage() {
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<Hit[]>([]);
  const [count, setCount] = useState<number | null>(null);
  const [open, setOpen] = useState<Hit | null>(null);

  const search = async (e: React.FormEvent) => {
    e.preventDefault();
    const { data } = await citationApi.searchArchive({ q });
    setHits(data.articles || []);
    setCount(data.count ?? 0);
  };

  const view = async (id: number) => {
    const { data } = await citationApi.getArticle(id);
    setOpen(data);
  };

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">Archive search</h2>
      <p className="text-gray-400 text-sm mb-4">
        Search stored full text across every journal in the persistent archive.
      </p>
      <form onSubmit={search} className="flex gap-2 max-w-xl mb-6">
        <input
          className="input-field"
          placeholder="Keyword, title, or author"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="btn-primary" type="submit">
          Search
        </button>
      </form>
      {count !== null && <p className="text-sm text-gray-500 mb-3">{count} results</p>}
      <div className="space-y-2">
        {hits.map((h) => (
          <button
            key={h.id}
            type="button"
            onClick={() => void view(h.id)}
            className="panel p-4 block w-full text-left hover:border-earth-500"
          >
            <p className="font-medium">{h.title}</p>
            <p className="text-sm text-gray-400">
              Vol. {h.volume} Issue {h.issue_number} · p.{h.page_start}
            </p>
            {h.snippet && <p className="text-xs text-gray-500 mt-2">{h.snippet}</p>}
          </button>
        ))}
      </div>
      {open && (
        <div className="panel p-4 mt-6">
          <div className="flex justify-between gap-4">
            <h3 className="font-medium">{open.title}</h3>
            <button className="btn-secondary" type="button" onClick={() => setOpen(null)}>
              Close
            </button>
          </div>
          <pre className="text-xs text-gray-300 whitespace-pre-wrap mt-3 max-h-[50vh] overflow-auto">
            {open.full_text || 'No stored text.'}
          </pre>
        </div>
      )}
    </div>
  );
}
