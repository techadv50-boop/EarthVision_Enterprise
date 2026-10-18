import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, errorText } from "../api";
import { formatPercent } from "../format";
import { useStudent } from "../store";
import type { ActiveExam, ProgressDashboard } from "../types";
import { Notice } from "../components/ui";

const cards = [
  { to: "/study", title: "My Classes", body: "Add classes, books, chapters, and topic notes." },
  { to: "/oral", title: "Go for an Oral Test", body: "Explain a chapter from memory, one topic at a time." },
  { to: "/written", title: "Go for a Written Test", body: "Take a timed paper made only from your notes." },
  { to: "/progress", title: "My Results and Progress", body: "See scores, missed ideas, and how you are doing." },
  { to: "/revision", title: "Topics Needing Revision", body: "Return to topics that were skipped or only partly recalled." },
  { to: "/settings", title: "Settings and Backup", body: "Theme, timers, offline models, backup, and restore." },
];

export function Dashboard() {
  const student = useStudent();
  const [progress, setProgress] = useState<ProgressDashboard | null>(null);
  const [exams, setExams] = useState<ActiveExam[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!student) return;
    let live = true;
    Promise.all([api.progress(student.id), api.listActiveExams(student.id)])
      .then(([nextProgress, nextExams]) => {
        if (!live) return;
        setProgress(nextProgress);
        setExams(nextExams);
      })
      .catch((err) => {
        if (live) setError(errorText(err));
      });
    return () => {
      live = false;
    };
  }, [student]);

  return (
    <div>
      <h1 className="text-4xl font-semibold tracking-tight">
        {student ? `Hello, ${student.displayName}` : "Welcome"}
      </h1>
      <p className="mt-2 max-w-3xl text-muted">
        Organize your notes, practice saying them back, and sit a written paper. Everything stays on this computer.
      </p>
      {!student ? (
        <div className="mt-6">
          <Notice tone="info">
            Create your student profile in <Link className="underline" to="/settings">Settings</Link> before adding classes.
          </Notice>
        </div>
      ) : null}
      {error ? <div className="mt-4"><Notice tone="error">{error}</Notice></div> : null}
      <div className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {cards.map((card) => (
          <Link
            key={card.to}
            to={card.to}
            className="rounded-3xl border border-line bg-card p-6 shadow-card transition hover:-translate-y-0.5"
          >
            <h2 className="text-2xl font-semibold">{card.title}</h2>
            <p className="mt-3 text-muted">{card.body}</p>
          </Link>
        ))}
      </div>
      {progress ? (
        <section className="mt-8 grid gap-4 sm:grid-cols-3">
          <Stat label="Tests completed" value={String(progress.testsCompleted)} />
          <Stat label="Average oral recall" value={formatPercent(progress.averageOral)} />
          <Stat label="Average written score" value={formatPercent(progress.averageWritten)} />
        </section>
      ) : null}
      {exams.length > 0 ? (
        <section className="mt-8">
          <h2 className="text-xl font-semibold">Exams still open</h2>
          <ul className="mt-3 space-y-2">
            {exams.map((exam) => (
              <li key={exam.examId}>
                <Link className="underline" to={`/exam/${exam.examId}`}>
                  {exam.className} · {exam.bookTitle} ({exam.status.replaceAll("_", " ")})
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-line bg-card p-4">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  );
}
