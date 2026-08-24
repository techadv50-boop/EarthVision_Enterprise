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
    setMsg(`Reading ${file.name}…`);
    try {
      const { data } = await citationApi.manuscripts.upload(file);
      setMsg('Matching against the journal archive…');
      await citationApi.manuscripts.suggest(data.id);
      await load();
      setMsg('Suggestions ready.');
    } catch {
      setMsg('Could not read that file. Upload a Word (.docx) or PDF manuscript.');
    }
  };

  const remove = async (id: number, title?: string) => {
    setMsg(`Removing ${title || 'manuscript'}…`);
    await citationApi.manuscripts.remove(id);
    await load();
    setMsg('Removed.');
  };

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">New manuscript</h2>
      <p className="text-gray-400 mb-4">
        Upload a Word document (.docx) or PDF. Citation suggestions come only from this journal’s
        archive.
      </p>
      <input
        type="file"
        accept=".docx,.pdf,.txt,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/pdf,text/plain"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.currentTarget.value = '';
          if (file) void upload(file);
        }}
      />
      {msg && <p className="text-earth-400 text-sm mt-2">{msg}</p>}
      <div className="mt-6 space-y-2">
        {items.map((m) => (
          <div key={m.id} className="panel p-4 flex items-start justify-between gap-3">
            <Link to={`/manuscripts/${m.id}`} className="block min-w-0 hover:text-earth-400">
              <p className="font-medium truncate">{m.title || `Manuscript ${m.id}`}</p>
              <p className="text-sm text-gray-400">
                {m.status} · {m.paragraph_count} paragraphs · {m.suggestion_count} suggestions
              </p>
            </Link>
            <button
              className="btn-secondary text-sm shrink-0"
              type="button"
              onClick={() => void remove(m.id, m.title)}
            >
              Remove
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
