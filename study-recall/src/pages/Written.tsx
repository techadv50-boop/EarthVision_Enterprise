import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, errorText } from "../api";
import { PlanModeSwitch, TimeChoices, type PlanMode } from "../components/TestChoice";
import { Crumbs, EmptyState, Notice, PageHeader, PrimaryButton, inputClass } from "../components/ui";
import { countNoun, formatClock, formatDuration } from "../format";
import { useStudent } from "../store";
import { MIX_LABELS, ORAL_TOPIC_SECONDS, estimateSeconds, fitMix, type QuestionMix, type QuestionSeconds } from "../testPlan";
import type { BookSummary, ChapterSummary, ClassSummary, Proposal } from "../types";
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
  const [mode, setMode] = useState<PlanMode>("time");
  const [minutes, setMinutes] = useState(30);
  const [seconds, setSeconds] = useState<QuestionSeconds>({ fib: 60, mcq: 45, short: 240, long: 600, oral: ORAL_TOPIC_SECONDS });
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
    setMode("time");
    setMinutes(30);
    api.listChapters(bookId, false).then(setChapters).catch((err) => setError(errorText(err)));
  }, [bookId]);

  useEffect(() => {
    api.getSettings().then((settings) => {
      setSeconds({
        fib: settings.fibSeconds,
        mcq: settings.mcqSeconds,
        short: settings.shortSeconds,
        long: settings.longSeconds,
        oral: ORAL_TOPIC_SECONDS,
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
      const caps = {
        fib: next.fibAvailable,
        mcq: next.mcqAvailable,
        short: next.shortAvailable,
        long: next.longAvailable,
        oral: capsOral,
      };
      setCounts((current) => mode === "time" ? fitMix(minutes * 60, caps, seconds) : {
        fib: Math.min(current.fib, caps.fib),
        mcq: Math.min(current.mcq, caps.mcq),
        short: Math.min(current.short, caps.short),
        long: Math.min(current.long, caps.long),
        oral: Math.min(current.oral, caps.oral),
      });
      setError("");
    }).catch((err) => {
      if (live) setError(errorText(err));
    });
    return () => {
      live = false;
    };
  }, [student, bookId, planKey, difficulty, selected, oralAvailable, seconds, mode, minutes]);

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

  function caps(): QuestionMix {
    return {
      fib: proposal?.fibAvailable ?? 0,
      mcq: proposal?.mcqAvailable ?? 0,
      short: proposal?.shortAvailable ?? 0,
      long: proposal?.longAvailable ?? 0,
      oral: oralAvailable,
    };
  }

  function chooseTime(nextMinutes: number) {
    setMode("time");
    setMinutes(nextMinutes);
    if (proposal) setCounts(fitMix(nextMinutes * 60, caps(), seconds));
  }

  function chooseCountMode() {
    setMode("count");
  }

  if (!student) return <Notice>Create a student profile before starting a written test.</Notice>;
  const className = classes.find((item) => item.id === classId)?.name;
  const bookTitle = books.find((item) => item.id === bookId)?.title;

  return (
    <div>
      <PageHeader
        title="Go for a Written Test"
        lede="Choose the chapters, then choose the test in one of two ways. Go by time, and the app lists how many of each question fit. Go by number of questions, and the app calculates the time that paper needs. Questions still come only from your notes."
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
              <PlanModeSwitch mode={mode} onChange={(next) => next === "time" ? chooseTime(minutes) : chooseCountMode()} />
              {mode === "time" ? (
                <div className="space-y-3">
                  <TimeChoices minutes={minutes} onChange={chooseTime} label="Time for the written test" />
                  <QuestionBreakdown counts={counts} seconds={seconds} chosenMinutes={minutes} />
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <CountField label="Fill in the blanks" max={proposal.fibAvailable} value={counts.fib} onChange={(fib) => setCounts({ ...counts, fib })} />
                    <CountField label="Multiple choice" max={proposal.mcqAvailable} value={counts.mcq} onChange={(mcq) => setCounts({ ...counts, mcq })} />
                    <CountField label="Short written questions" max={proposal.shortAvailable} value={counts.short} onChange={(short) => setCounts({ ...counts, short })} />
                    <CountField label="Long written questions" max={proposal.longAvailable} value={counts.long} onChange={(long) => setCounts({ ...counts, long })} />
                    <CountField label="Oral recall topics" max={oralAvailable} value={counts.oral} onChange={(oral) => setCounts({ ...counts, oral })} />
                  </div>
                  <QuestionBreakdown counts={counts} seconds={seconds} />
                </div>
              )}
              <p className="text-sm text-muted">
                Marks follow the questions: 3 for each blank, 2 for each multiple-choice question, 5 for each short question, and 15 for each long question. Oral topics are scored separately and have no countdown.
              </p>
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

function QuestionBreakdown({ counts, seconds, chosenMinutes }: { counts: QuestionMix; seconds: QuestionSeconds; chosenMinutes?: number }) {
  const used = estimateSeconds(counts, seconds);
  const rows = MIX_LABELS.filter((row) => counts[row.key] > 0);
  const periodLabel = chosenMinutes == null ? "" : chosenMinutes >= 60 && chosenMinutes % 60 === 0
    ? `${chosenMinutes / 60} ${chosenMinutes === 60 ? "hour" : "hours"}`
    : `${chosenMinutes} minutes`;
  return (
    <div className="rounded-xl border border-line p-4">
      <h3 className="font-semibold">
        {chosenMinutes == null ? "Time allocated for this paper" : `Questions that fit in ${periodLabel}`}
      </h3>
      {rows.length === 0 ? <p className="mt-2 text-sm">These notes cannot support a question in this choice.</p> : (
        <ul className="mt-2 space-y-1 text-sm">
          {rows.map((row) => (
            <li key={row.key}>
              {countNoun(counts[row.key], row.singular, row.plural)} · {formatClock(seconds[row.key] * 1000)} each · {formatDuration(counts[row.key] * seconds[row.key])}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-sm font-medium">Time for this paper: {formatDuration(used)}.</p>
      {chosenMinutes != null && used < chosenMinutes * 60 ? (
        <p className="mt-1 text-sm text-muted">The notes run out before the full period. This is the longest mix they can support.</p>
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
