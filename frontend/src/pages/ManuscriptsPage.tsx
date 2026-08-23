import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { citationApi } from '@/services/api';

interface Ms {
  id: number;
  title?: string;
  status: string;
  suggestion_count: number;
  paragraph_count: number;
}

export default function ManuscriptsPage() {
  const [items, setItems] = useState<Ms[]>([]);
  const [msg, setMsg] = useState('');

  const load = async () => {
    const { data } = await citationApi.manuscripts.list();
    setItems(data);
  };

  useEffect(() => {
    void load();
  }, []);

  const upload = async (file: File) => {
    setMsg('Reading manuscript…');
    const { data } = await citationApi.manuscripts.upload(file);
    setMsg('Matching against the archive…');
    await citationApi.manuscripts.suggest(data.id);
    await load();
    setMsg('Suggestions ready.');
  };

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">New manuscript</h2>
      <p className="text-gray-400 mb-4">
        Upload a paper to be published. Suggestions come from the same persistent journal archive.
      </p>
      <input
        type="file"
        accept=".pdf,.txt"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void upload(f);
        }}
      />
      {msg && <p className="text-earth-400 text-sm mt-2">{msg}</p>}
      <div className="mt-6 space-y-2">
        {items.map((m) => (
          <Link key={m.id} to={`/manuscripts/${m.id}`} className="panel p-4 block hover:border-earth-500">
            <p className="font-medium">{m.title || `Manuscript ${m.id}`}</p>
            <p className="text-sm text-gray-400">
              {m.status} · {m.paragraph_count} paragraphs · {m.suggestion_count} suggestions
            </p>
          </Link>
        ))}
      </div>
    </div>
  );
}
