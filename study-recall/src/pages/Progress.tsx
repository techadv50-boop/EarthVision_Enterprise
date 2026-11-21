import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, errorText } from "../api";
import { Notice, PageHeader } from "../components/ui";
import { formatPercent, statusLabel } from "../format";
import { useStudent } from "../store";
import type { GroupScore, ProgressDashboard } from "../types";

export function Progress() {
  const student = useStudent();
  const [data, setData] = useState<ProgressDashboard | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!student) return;
    api.progress(student.id).then(setData).catch((err) => setError(errorText(err)));
  }, [student]);

  if (!student) return <Notice>Create a student profile to see progress.</Notice>;
  if (!data && !error) return <p>Loading progress…</p>;
  if (!data) return <Notice tone="error">{error}</Notice>;

  return (
    <div>
      <PageHeader
        title="My Results and Progress"
        lede={`Well remembered is ${data.wellRememberedPercent}% or above. Developing is ${data.developingPercent}% up to that line. Older results stay in the history.`}
      />
      {error ? <div className="mb-4"><Notice tone="error">{error}</Notice></div> : null}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile label="Tests completed" value={String(data.testsCompleted)} />
        <Tile label="Oral sessions" value={String(data.oralSessions)} />
        <Tile label="Written exams" value={String(data.writtenExams)} />
        <Tile label="Average oral" value={formatPercent(data.averageOral)} />
        <Tile label="Average written" value={formatPercent(data.averageWritten)} />
        <Tile label={statusLabel("needs_revision")} value={String(data.needsRevision)} />
        <Tile label={statusLabel("developing")} value={String(data.developing)} />
        <Tile label={statusLabel("well_remembered")} value={String(data.wellRemembered)} />
        <Tile label="Not tested" value={String(data.untested)} />
        <Tile label="Revision events" value={String(data.revisionCompleted)} />
      </div>
      <div className="mt-6">
        <Link className="underline" to="/revision">Open topics that need revision</Link>
      </div>
      <Chart title="Recent written examinations" points={data.recentWritten} />
      <Chart title="Recent oral tests" points={data.recentOral} />
      <Groups title="By class" rows={data.byClass} />
      <Groups title="By subject" rows={data.byBook} />
      <Groups title="By chapter" rows={data.byChapter} />
      <Groups title="By topic" rows={data.byTopic} />
      <section className="mt-8">
        <h2 className="text-xl font-semibold">Frequently missed concepts</h2>
        {data.missedConcepts.length === 0 ? <p className="mt-2 text-muted">None recorded yet.</p> : (
          <ul className="mt-3 space-y-2">
            {data.missedConcepts.map((item) => (
              <li key={item.concept} className="rounded-xl border border-line bg-card px-4 py-2">
                {item.concept} <span className="text-muted">· missed {item.count} times</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-line bg-card p-4">
      <p className="text-sm text-muted">{label}</p>
      <p className="text-2xl font-semibold">{value}</p>
    </div>
  );
}

function Chart({ title, points }: { title: string; points: ProgressDashboard["recentWritten"] }) {
  return (
    <section className="mt-8">
      <h2 className="text-xl font-semibold">{title}</h2>
      {points.length === 0 ? <p className="mt-2 text-muted">No scores yet.</p> : (
        <ul className="mt-3 space-y-2">
          {points.map((point) => (
            <li key={point.id}>
              <div className="mb-1 flex justify-between text-sm">
                <span>{point.label}</span>
                <span>{formatPercent(point.percentage)}</span>
              </div>
              <div className="h-3 rounded-full bg-line">
                <div className="h-3 rounded-full bg-accent" style={{ width: `${Math.max(0, Math.min(100, point.percentage))}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Groups({ title, rows }: { title: string; rows: GroupScore[] }) {
  return (
    <section className="mt-8">
      <h2 className="text-xl font-semibold">{title}</h2>
      {rows.length === 0 ? <p className="mt-2 text-muted">No scores yet.</p> : (
        <ul className="mt-3 divide-y divide-line rounded-2xl border border-line bg-card">
          {rows.map((row) => (
            <li key={row.id} className="flex flex-wrap justify-between gap-2 px-4 py-3">
              <span>
                {row.label}
                {row.parentLabel ? <span className="ml-2 text-sm text-muted">{row.parentLabel}</span> : null}
              </span>
              <span className="text-sm">{formatPercent(row.averagePercent)} · {row.attempts} attempts</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
