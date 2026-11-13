import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, errorText } from "../api";
import { Crumbs, EmptyState, Notice, PageHeader, PrimaryButton, QuietButton, inputClass } from "../components/ui";
import { countNoun, formatClock } from "../format";
import { useStudent } from "../store";
import { estimateSeconds, fitMix, useAll, type QuestionMix, type QuestionSeconds } from "../testPlan";
import type { BookSummary, ChapterSummary, ClassSummary, Proposal } from "../types";

const ORAL_SECONDS = 180;
const PENDING_ORAL = "study-recall-pending-oral";

const emptyMix: QuestionMix = { fib: 0, mcq: 0, short: 0, long: 0, oral: 0 };

export function Written() {
  const { classId = "", bookId = "" } = useParams();
  const student = useStudent();
  const navigate = useNavigate();
  const [classes, setClasses] = useState<ClassSummary[]>([]);
  const [books, setBooks] = useState<BookSummary[]>([]);
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [difficulty, setDifficulty] = useState("standard");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [counts, setCounts] = useState<QuestionMix>(emptyMix);
  const [seconds, setSeconds] = useState<QuestionSeconds>({ fib: 60, mcq: 45, short: 240, long: 600, oral: ORAL_SECONDS });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!student) return;
    api.listClasses(student.id, false).then(setClasses).catch((err) => setError(errorText(err)));
  }, [student]);
  useEffect(() => {
    if (!classId) return;
    api.listBooks(classId, false).then(setBooks).catch((err) => setError(errorText(err)));
  }, [classId]);
  useEffect(() => {
    if (!bookId) return;
    setProposal(null);
    setSelected([]);
    setCounts(emptyMix);
    api.listChapters(bookId, false).then(setChapters).catch((err) => setError(errorText(err)));
  }, [bookId]);

  useEffect(() => {
    api.getSettings().then((settings) => {
      setSeconds({
        fib: settings.fibSeconds,
        mcq: settings.mcqSeconds,
        short: settings.shortSeconds,
        long: settings.longSeconds,
        oral: ORAL_SECONDS,
      });
    }).catch(() => undefined);
  }, []);

  const oralAvailable = chapters.filter((chapter) => selected.includes(chapter.id)).reduce((sum, chapter) => sum + chapter.studiedTopicCount, 0);
  const planKey = `${difficulty}:${[...selected].sort().join(",")}`;

  useEffect(() => {
    if (!student || selected.length === 0) {
      setProposal(null);
      return;
    }
    let live = true;
    const capsOral = oralAvailable;
    api.proposeExam(student.id, bookId, selected, difficulty).then((next) => {
      if (!live) return;
      setProposal(next);
      setCounts(fitMix(30 * 60, {
        fib: next.fibAvailable,
        mcq: next.mcqAvailable,
        short: next.shortAvailable,
        long: next.longAvailable,
        oral: capsOral,
      }, seconds));
      setError("");
    }).catch((err) => {
      if (live) setError(errorText(err));
    });
    return () => {
      live = false;
    };
  }, [student, bookId, planKey, difficulty, selected, oralAvailable, seconds]);

  async function start() {
    if (!student) return;
    const written = counts.fib + counts.mcq + counts.short + counts.long;
    if (written === 0 && counts.oral === 0) {
      setError("Choose at least one question.");
      return;
    }
    setBusy(true);
    try {
      if (written === 0) {
        sessionStorage.removeItem(PENDING_ORAL);
        const prompt = await api.startOralChapters(student.id, selected, counts.oral);
        navigate(`/oral/session/${prompt.sessionId}`, { state: { prompt } });
        return;
      }
      const created = await api.createExam(student.id, bookId, selected, difficulty, counts);
      if (counts.oral > 0) {
        sessionStorage.setItem(PENDING_ORAL, JSON.stringify({ chapterIds: selected, topicLimit: counts.oral }));
      } else {
        sessionStorage.removeItem(PENDING_ORAL);
      }
      navigate(`/exam/${created.examId}`);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  function applyFit(minutes: number) {
    if (!proposal) return;
    setCounts(fitMix(minutes * 60, {
      fib: proposal.fibAvailable,
      mcq: proposal.mcqAvailable,
      short: proposal.shortAvailable,
      long: proposal.longAvailable,
      oral: oralAvailable,
    }, seconds));
  }

  if (!student) return <Notice>Create a student profile before starting a written test.</Notice>;
  const className = classes.find((item) => item.id === classId)?.name;
  const bookTitle = books.find((item) => item.id === bookId)?.title;

  return (
    <div>
      <PageHeader
        title="Go for a Written Test"
        lede="Choose the chapters, then choose how many questions of each type you want. A short time, such as 30 minutes, can be a small test. A longer time can use more questions. Questions still come only from your notes."
      />
      {error ? <div className="mb-4"><Notice tone="error">{error}</Notice></div> : null}
      <Crumbs
        items={[
          { label: "Classes", to: "/written" },
          ...(classId ? [{ label: className ?? "Class", to: `/written/${classId}` }] : []),
          ...(bookId ? [{ label: bookTitle ?? "Book" }] : []),
        ]}
      />
      {!classId ? <Grid empty="No classes yet." items={classes.map((item) => ({ id: item.id, title: item.name, to: `/written/${item.id}` }))} /> : null}
      {classId && !bookId ? <Grid empty="No books in this class." items={books.map((item) => ({ id: item.id, title: item.title, to: `/written/${classId}/${item.id}` }))} /> : null}
      {bookId ? (
        <section className="rounded-2xl border border-line bg-card p-5">
          {chapters.length === 0 ? <EmptyState title="No chapters have been added to this book." body="Add a chapter and save topic notes before generating a paper." /> : null}
          <ul className="space-y-2">
            {chapters.map((chapter) => (
              <li key={chapter.id}>
                <label className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={selected.includes(chapter.id)}
                    onChange={(event) => {
                      setProposal(null);
                      setSelected(event.target.checked ? [...selected, chapter.id] : selected.filter((id) => id !== chapter.id));
                    }}
                  />
                  <span>
                    {chapter.title}
                    <span className="ml-2 text-sm text-muted">{countNoun(chapter.studiedTopicCount, "topic")} with notes</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <label className="mt-4 block max-w-xs text-sm font-medium">
            Difficulty
            <select className={`${inputClass} mt-1`} value={difficulty} onChange={(event) => { setDifficulty(event.target.value); setProposal(null); }}>
              <option value="easy">Easy</option>
              <option value="standard">Standard</option>
              <option value="hard">Hard</option>
            </select>
          </label>
          {proposal ? (
            <div className="mt-5 space-y-4">
              <Notice>{proposal.materialNote}</Notice>
              {proposal.difficultyNote ? <p className="text-sm text-muted">{proposal.difficultyNote}</p> : null}
              <p className="text-sm text-muted">
                These notes can support {proposal.fibAvailable} blanks, {proposal.mcqAvailable} multiple choice, {proposal.shortAvailable} short, {proposal.longAvailable} long, and {oralAvailable} oral topics.
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <CountField label="Fill in the blanks" max={proposal.fibAvailable} value={counts.fib} onChange={(fib) => setCounts({ ...counts, fib })} />
                <CountField label="Multiple choice" max={proposal.mcqAvailable} value={counts.mcq} onChange={(mcq) => setCounts({ ...counts, mcq })} />
                <CountField label="Short written questions" max={proposal.shortAvailable} value={counts.short} onChange={(short) => setCounts({ ...counts, short })} />
                <CountField label="Long written questions" max={proposal.longAvailable} value={counts.long} onChange={(long) => setCounts({ ...counts, long })} />
                <CountField label="Oral recall topics" max={oralAvailable} value={counts.oral} onChange={(oral) => setCounts({ ...counts, oral })} />
              </div>
              <p className="text-sm">
                Estimated time {formatClock(estimateSeconds(counts, seconds) * 1000)}. Written questions use the timers in Settings. Each oral topic is planned as about 3 minutes and has no countdown.
              </p>
              <p className="text-sm text-muted">
                Marks follow the questions you choose: 3 for each blank, 2 for each multiple-choice question, 5 for each short question, and 15 for each long question. Oral topics are scored separately.
              </p>
              <div className="flex flex-wrap gap-2">
                <QuietButton onClick={() => applyFit(15)}>About 15 minutes</QuietButton>
                <QuietButton onClick={() => applyFit(30)}>About 30 minutes</QuietButton>
                <QuietButton onClick={() => applyFit(60)}>About 60 minutes</QuietButton>
                <QuietButton onClick={() => setCounts(useAll({
                  fib: proposal.fibAvailable,
                  mcq: proposal.mcqAvailable,
                  short: proposal.shortAvailable,
                  long: proposal.longAvailable,
                  oral: oralAvailable,
                }))}>Use every available question</QuietButton>
              </div>
              <PrimaryButton disabled={busy} onClick={() => void start()}>
                {busy ? "Starting…" : "Start this test"}
              </PrimaryButton>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function CountField({ label, value, max, onChange }: { label: string; value: number; max: number; onChange: (value: number) => void }) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <span className="ml-2 font-normal text-muted">up to {max}</span>
      <input
        className={`${inputClass} mt-1`}
        type="number"
        min={0}
        max={max}
        value={value}
        disabled={max === 0}
        onChange={(event) => onChange(Math.min(max, Math.max(0, Number(event.target.value) || 0)))}
      />
    </label>
  );
}

function Grid({ items, empty }: { items: { id: string; title: string; to: string }[]; empty: string }) {
  if (items.length === 0) return <EmptyState title={empty} body="Add study material first." />;
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {items.map((item) => (
        <li key={item.id}>
          <Link className="block rounded-2xl border border-line bg-card p-5 text-xl font-semibold" to={item.to}>{item.title}</Link>
        </li>
      ))}
    </ul>
  );
}
