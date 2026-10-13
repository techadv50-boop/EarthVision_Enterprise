import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';
import { citationApi } from '@/services/api';

interface IssueRow {
  id: number;
  volume: number;
  issue_number: number;
  year?: number;
  month?: string;
  article_count: number;
  cited_count: number;
  uncited_count: number;
  scholar_total: number;
  crossref_total: number;
  citations_synced?: boolean;
}

export default function VolumeIssuesPage() {
  const { journalId, volume } = useParams();
  const id = Number(journalId);
  const vol = Number(volume);
  const [issues, setIssues] = useState<IssueRow[]>([]);

  const load = async () => {
    const { data } = await citationApi.journals.issues(id, vol);
    setIssues(data);
    return data as IssueRow[];
  };

  useEffect(() => {
    void load();
  }, [id, vol]);

  return (
    <div>
      <p className="text-sm text-gray-500 mb-2">
        <Link to="/">Journals</Link> / <Link to={`/journals/${id}`}>Journal</Link> /{' '}
        {vol === 0 ? 'Unfiled' : `Vol. ${vol}`}
      </p>
      <h2 className="text-2xl font-semibold mb-2">{vol === 0 ? 'Unfiled papers' : `Volume ${vol}`}</h2>
      <p className="text-gray-400 mb-6">
        {vol === 0
          ? 'These PDFs could not be placed in a volume. Open an issue rack and upload, or use File unfiled papers on the journal page.'
          : 'Each issue shows how many articles live there. Empty racks are listed so missing issues can be uploaded into place.'}
      </p>
      <div className="grid md:grid-cols-2 gap-4">
        {issues.map((iss) => {
          const cited = Number(iss.cited_count ?? (iss as { cited_count?: number }).cited_count ?? 0);
          const uncited = Number(iss.uncited_count ?? (iss as { uncited_count?: number }).uncited_count ?? 0);
          const scholar = Number(iss.scholar_total ?? (iss as { scholar_total?: number }).scholar_total ?? 0);
          const crossref = Number(iss.crossref_total ?? (iss as { crossref_total?: number }).crossref_total ?? 0);
          const articles = Number(iss.article_count ?? (iss as { article_count?: number }).article_count ?? 0);
          const data = [
            { name: 'Cited', value: cited },
            { name: 'Not cited', value: uncited },
          ];
          const empty = articles === 0;
          return (
            <Link
              key={`${iss.issue_number}-${iss.id}`}
              to={`/journals/${id}/volumes/${vol}/issues/${iss.issue_number}`}
              className="panel p-4 block"
            >
              <div className="flex justify-between">
                <h3 className="font-medium">
                  {vol === 0 ? 'Unfiled' : `Issue ${iss.issue_number}`}
                  {iss.month ? ` · ${iss.month} ${iss.year ?? ''}` : ''}
                </h3>
                <span className="text-gray-400 text-sm">{articles} articles</span>
              </div>
              {iss.id === 0 || empty ? (
                <p className="text-amber-300 text-sm mt-3">
                  Issue missing from archive — open this rack and upload the PDFs.
                </p>
              ) : (
                <>
                  <p className="text-sm text-gray-400 mt-2">
                    {cited} cited · Scholar {scholar} · Crossref {crossref} · {uncited} not cited
                  </p>
                  <div className="h-40 mt-2">
                    <ResponsiveContainer>
                      <PieChart>
                        <Pie data={data} dataKey="value" innerRadius={40} outerRadius={60}>
                          <Cell fill="#60a5fa" />
                          <Cell fill="#6b7280" />
                        </Pie>
                        <Tooltip />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                </>
              )}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
