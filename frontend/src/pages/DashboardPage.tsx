import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Plus, Trash2 } from 'lucide-react';
import { citationApi } from '@/services/api';

interface Journal {
  id: number;
  name: string;
  abbreviation?: string;
  article_count: number;
  volume_count: number;
  has_gaps: boolean;
}

export default function DashboardPage() {
  const [journals, setJournals] = useState<Journal[]>([]);
  const [name, setName] = useState('International Journal of Innovations in Science & Technology');
  const [abbr, setAbbr] = useState('IJIST');
  const [archiveUrl, setArchiveUrl] = useState(
    'https://journal.50sea.com/index.php/IJIST/issue/archive'
  );
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    const { data } = await citationApi.journals.list();
    setJournals(data);
  };

  useEffect(() => {
    void load();
  }, []);

  const remove = async (id: number, title: string) => {
    if (!window.confirm(`Remove “${title}” from this shelf? Papers stored under it will be deleted.`)) {
      return;
    }
    await citationApi.journals.remove(id);
    await load();
  };

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await citationApi.journals.create({
        name,
        abbreviation: abbr,
        publisher: '50Sea',
        archive_url: archiveUrl,
      });
      setOpen(false);
      await load();
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      setError(
        status === 409
          ? 'That journal is already on the shelf. Open the existing card instead of adding it again.'
          : 'Could not create journal'
      );
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-semibold">Journals</h2>
          <p className="text-gray-400 text-sm mt-1">
            Each card shows the journal name and how many articles are stored in the archive.{' '}
            <Link to="/archive" className="text-earth-400 hover:underline">
              Search the archive
            </Link>
          </p>
        </div>
        <button className="btn-primary inline-flex items-center gap-2" onClick={() => setOpen(true)}>
          <Plus className="w-4 h-4" /> Add journal
        </button>
      </div>

      {open && (
        <form onSubmit={create} className="panel p-4 mb-6 space-y-3 max-w-xl">
          <input className="input-field" value={name} onChange={(e) => setName(e.target.value)} />
          <input className="input-field" value={abbr} onChange={(e) => setAbbr(e.target.value)} />
          <input
            className="input-field"
            placeholder="Archive URL"
            value={archiveUrl}
            onChange={(e) => setArchiveUrl(e.target.value)}
          />
          {error && <p className="text-red-400 text-sm">{error}</p>}
          <div className="flex gap-2">
            <button className="btn-primary" type="submit">
              Save
            </button>
            <button className="btn-secondary" type="button" onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        {journals.map((j) => (
          <Link
            key={j.id}
            to={`/journals/${j.id}`}
            className="panel p-5 hover:border-earth-500 transition-colors block"
          >
            <div className="flex justify-between items-start">
              <h3 className="font-semibold text-lg pr-4">{j.name}</h3>
              <div className="flex items-center gap-2 shrink-0">
                {j.has_gaps && (
                  <span className="text-xs bg-amber-900/50 text-amber-300 px-2 py-1 rounded">
                    Gaps
                  </span>
                )}
                <button
                  type="button"
                  className="p-1 text-gray-500 hover:text-red-400"
                  title="Remove journal"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    void remove(j.id, j.name);
                  }}
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
            <p className="text-gray-400 text-sm mt-1">{j.abbreviation}</p>
            <p className="mt-4 text-3xl font-bold text-earth-400">{j.article_count}</p>
            <p className="text-sm text-gray-500">articles in archive · {j.volume_count} volumes</p>
          </Link>
        ))}
        {journals.length === 0 && (
          <p className="text-gray-500">No journals yet. Add IJIST to start the archive.</p>
        )}
      </div>
    </div>
  );
}
