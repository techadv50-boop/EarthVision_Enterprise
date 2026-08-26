import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { citationApi } from '@/services/api';

export default function ManuscriptReviewPage() {
  const { manuscriptId } = useParams();
  const id = Number(manuscriptId);
  const [title, setTitle] = useState('');
  const [counts, setCounts] = useState({ paragraphs: 0, suggestions: 0 });
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void citationApi.manuscripts.get(id).then(({ data }) => {
      setTitle(data.title || `Manuscript ${id}`);
      const suggestions = (data.paragraphs || []).reduce(
        (n: number, p: { suggestions?: unknown[] }) => n + (p.suggestions?.length || 0),
        0,
      );
      setCounts({ paragraphs: (data.paragraphs || []).length, suggestions });
    });
  }, [id]);

  const downloadWord = async () => {
    setBusy(true);
    setMsg('Building Word file…');
    try {
      const { data } = await citationApi.manuscripts.export(id);
      const blob = data instanceof Blob ? data : new Blob([data]);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const stem = (title || 'manuscript').replace(/\.[^.]+$/, '');
      a.href = url;
      a.download = `${stem}-suggestions.docx`;
      a.click();
      URL.revokeObjectURL(url);
      setMsg('Word file downloaded.');
    } catch {
      setMsg('Export failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-2xl">
      <p className="text-sm text-gray-500 mb-3">
        <Link to="/manuscripts">Manuscripts</Link> / {title}
      </p>
      <h2 className="text-2xl font-semibold mb-2">{title}</h2>
      <p className="text-sm text-gray-400 mb-6">
        {counts.paragraphs} paragraphs · {counts.suggestions} suggestions
      </p>
      <p className="text-gray-300 mb-6">
        Download the Word file and review it in Microsoft Word. Each suggested citation is a
        tracked change with a comment explaining why it was suggested, including journal,
        volume, issue, pages, and DOI when stored. The matching reference is a shared endnote
        for that archive article. Accept keeps both; Reject removes this citation. If you reject
        every citation to the same article, reject that endnote so the reference is not left behind.
      </p>
      <button className="btn-primary" type="button" disabled={busy} onClick={() => void downloadWord()}>
        Download Word file
      </button>
      {msg && <p className="text-earth-400 text-sm mt-4">{msg}</p>}
    </div>
  );
}
