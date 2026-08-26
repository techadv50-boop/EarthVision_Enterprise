import { useEffect, useState } from 'react';
import { citationApi } from '@/services/api';

interface Ms {
  id: number;
  title?: string;
  status: string;
  suggestion_count: number;
  paragraph_count: number;
}

function downloadBlob(data: Blob, filename: string) {
  const blob = data instanceof Blob ? data : new Blob([data]);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function ManuscriptsPage() {
  const [items, setItems] = useState<Ms[]>([]);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const { data } = await citationApi.manuscripts.list();
    setItems(data);
  };

  useEffect(() => {
    void load();
  }, []);

  const downloadReview = async (id: number, title?: string) => {
    const { data } = await citationApi.manuscripts.export(id);
    const stem = (title || 'manuscript').replace(/\.[^.]+$/, '');
    downloadBlob(data, `${stem}-suggestions.docx`);
  };

  const upload = async (file: File) => {
    setBusy(true);
    setMsg(`Reading ${file.name} paragraph by paragraph…`);
    try {
      const { data } = await citationApi.manuscripts.upload(file);
      setMsg('Matching each paragraph against the journal archive…');
      await citationApi.manuscripts.suggest(data.id);
      setMsg('Building a Word file with Accept / Reject suggestions…');
      await downloadReview(data.id, data.title || file.name);
      await load();
      setMsg(
        'Downloaded. Open it in Word → Review. Accept keeps the citation and its reference; Reject removes both. Each comment explains why it was suggested.',
      );
    } catch {
      setMsg('Could not read that file. Upload a Word (.docx) or PDF manuscript.');
    } finally {
      setBusy(false);
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
      <p className="text-gray-400 mb-4 max-w-3xl">
        Upload a Word document. The system reads it paragraph by paragraph and matches
        substantive paragraphs against articles already stored in Citation Assistant. It
        keeps at most ten of the strongest matches for the whole manuscript, and at most
        one match per paragraph — not every paragraph gets a citation. Open that file in
        Microsoft Word and use <span className="text-gray-200">Review → Accept or Reject</span>.
        Each comment explains why the citation was suggested. The matching reference is the
        shared endnote for that archive article — accepting keeps citation and reference;
        rejecting the last citation to that article also drops its reference.
      </p>
      <input
        type="file"
        disabled={busy}
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
            <div className="min-w-0">
              <p className="font-medium truncate">{m.title || `Manuscript ${m.id}`}</p>
              <p className="text-sm text-gray-400">
                {m.status} · {m.paragraph_count} paragraphs · {m.suggestion_count} suggestions
              </p>
            </div>
            <div className="flex gap-2 shrink-0">
              <button
                className="btn-primary text-sm"
                type="button"
                disabled={busy}
                onClick={() => void downloadReview(m.id, m.title).then(() => setMsg('Word file downloaded.'))}
              >
                Download Word file
              </button>
              <button
                className="btn-secondary text-sm"
                type="button"
                onClick={() => void remove(m.id, m.title)}
              >
                Remove
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
