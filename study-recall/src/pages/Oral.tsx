import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, errorText } from "../api";
import { Recorder } from "../components/Recorder";
import { SpeakButton } from "../components/SpeakButton";
import { Crumbs, EmptyState, Notice, PageHeader, PrimaryButton, QuietButton, inputClass } from "../components/ui";
import { countNoun, formatPercent, statusLabel } from "../format";
import { useStudent } from "../store";
import type { BookSummary, ChapterSummary, ClassSummary, OralPrompt, OralSummary, OralTopicResult } from "../types";

export function Oral() {
  const { sessionId } = useParams();
  if (sessionId) return <OralSession sessionId={sessionId} />;
  return <OralPicker />;
}

function OralPicker() {
  const { classId = "", bookId = "", chapterId = "" } = useParams();
  const student = useStudent();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [classes, setClasses] = useState<ClassSummary[]>([]);
  const [books, setBooks] = useState<BookSummary[]>([]);
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [readyCount, setReadyCount] = useState(0);

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
    api.listChapters(bookId, false).then(setChapters).catch((err) => setError(errorText(err)));
  }, [bookId]);

  useEffect(() => {
    if (!chapterId) return;
    api.listTopics(chapterId, false).then((topics) => setReadyCount(topics.filter((topic) => topic.hasReference).length)).catch((err) => setError(errorText(err)));
  }, [chapterId]);

  async function start() {
    if (!student) return;
    try {
      const prompt = await api.startOral(student.id, chapterId);
      navigate(`/oral/session/${prompt.sessionId}`, { state: { prompt } });
    } catch (err) {
      setError(errorText(err));
    }
  }

  if (!student) return <Notice>Create a student profile before starting an oral test.</Notice>;
  const className = classes.find((item) => item.id === classId)?.name;
  const bookTitle = books.find((item) => item.id === bookId)?.title;

  return (
    <div>
      <PageHeader title="Go for an Oral Test" lede="Choose a chapter. Topics are shuffled and each one is asked once." />
      {error ? <div className="mb-4"><Notice tone="error">{error}</Notice></div> : null}
      <Crumbs
        items={[
          { label: "Classes", to: "/oral" },
          ...(classId ? [{ label: className ?? "Class", to: `/oral/${classId}` }] : []),
          ...(bookId ? [{ label: bookTitle ?? "Book", to: `/oral/${classId}/${bookId}` }] : []),
          ...(chapterId ? [{ label: chapters.find((item) => item.id === chapterId)?.title ?? "Chapter" }] : []),
        ]}
      />
      {!classId ? <ChoiceList empty="No classes yet. Add one in Study material." items={classes.map((item) => ({ id: item.id, title: item.name, to: `/oral/${item.id}` }))} /> : null}
      {classId && !bookId ? <ChoiceList empty="No books have been added to this class." items={books.map((item) => ({ id: item.id, title: item.title, to: `/oral/${classId}/${item.id}` }))} /> : null}
      {bookId && !chapterId ? <ChoiceList empty="No chapters have been added to this book." items={chapters.map((item) => ({ id: item.id, title: item.title, meta: `${countNoun(item.studiedTopicCount, "topic")} with notes`, to: `/oral/${classId}/${bookId}/${item.id}` }))} /> : null}
      {chapterId ? (
        <section className="rounded-2xl border border-line bg-card p-6">
          <p>{readyCount === 0 ? "This chapter has no topics with saved notes." : `${countNoun(readyCount, "topic")} with notes will be shuffled.`}</p>
          <div className="mt-4">
            <PrimaryButton disabled={readyCount === 0} onClick={() => void start()}>Start oral test</PrimaryButton>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function ChoiceList({ items, empty }: { items: { id: string; title: string; to: string; meta?: string }[]; empty: string }) {
  if (items.length === 0) return <EmptyState title={empty} body="Add the missing study material, then come back." />;
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {items.map((item) => (
        <li key={item.id}>
          <Link className="block rounded-2xl border border-line bg-card p-5 text-xl font-semibold" to={item.to}>
            {item.title}
            {item.meta ? <span className="mt-1 block text-sm font-normal text-muted">{item.meta}</span> : null}
          </Link>
        </li>
      ))}
    </ul>
  );
}

function OralSession({ sessionId }: { sessionId: string }) {
  const location = useLocation();
  const locationPrompt = ((location.state as { prompt?: OralPrompt } | null)?.prompt) ?? null;
  const [prompt, setPrompt] = useState<OralPrompt | null>(locationPrompt);
  const [result, setResult] = useState<OralTopicResult | null>(null);
  const [summary, setSummary] = useState<OralSummary | null>(null);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (locationPrompt) return;
    let live = true;
    api.getOralPrompt(sessionId).then(async (next) => {
      if (!live) return;
      if (next) setPrompt(next);
      else setSummary(await api.oralSummary(sessionId));
    }).catch((err) => {
      if (live) setError(errorText(err));
    });
    return () => {
      live = false;
    };
  }, [locationPrompt, sessionId]);

  async function submit(skipped: boolean) {
    setBusy(true);
    try {
      const step = skipped ? await api.skipOral(sessionId) : await api.submitOral(sessionId, transcript);
      setResult(step.result);
      setTranscript("");
      if (step.finished && step.summary) {
        setSummary(step.summary);
        setPrompt(null);
      } else {
        setPrompt(null);
      }
      setError("");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function nextTopic() {
    const next = await api.getOralPrompt(sessionId);
    setResult(null);
    setPrompt(next);
  }

  if (summary) return <OralReport summary={summary} />;

  return (
    <div>
      <PageHeader title="Oral recall" lede="Explain the topic in your own words. A skip is recorded as skipped, not as correct." />
      {error ? <div className="mb-4"><Notice tone="error">{error}</Notice></div> : null}
      {prompt ? (
        <article key={prompt.topicId} className="recall-card rounded-3xl border border-line bg-card p-6 shadow-card">
          <p className="text-sm text-muted">
            {prompt.className} · {prompt.bookTitle} · {prompt.chapterTitle} · Topic {prompt.position + 1} of {prompt.total}
          </p>
          <h2 className="mt-3 text-3xl font-semibold" dir={prompt.textDirection} lang={prompt.language}>
            Explain the topic: {prompt.topicTitle}
          </h2>
          <div className="mt-3">
            <SpeakButton text={`Explain the topic: ${prompt.topicTitle}`} language={prompt.language} />
          </div>
          <div className="mt-5">
            <Recorder
              language={prompt.language}
              onTranscript={(text) => setTranscript((current) => (current.trim() ? `${current.trim()}\n${text}` : text))}
            />
          </div>
          <label className="mt-4 block text-sm font-medium">
            Answer transcript
            <textarea className={`${inputClass} mt-1 min-h-36`} dir={prompt.textDirection} lang={prompt.language} value={transcript} onChange={(event) => setTranscript(event.target.value)} />
          </label>
          <div className="mt-4 flex flex-wrap gap-2">
            <PrimaryButton disabled={busy || !transcript.trim()} onClick={() => void submit(false)}>Submit answer</PrimaryButton>
            <QuietButton disabled={busy} onClick={() => void submit(true)}>Skip topic</QuietButton>
          </div>
        </article>
      ) : null}
      {result && !summary ? (
        <section className="mt-6">
          <Feedback result={result} />
          <div className="mt-4">
            <PrimaryButton onClick={() => void nextTopic()}>Next topic</PrimaryButton>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function Feedback({ result }: { result: OralTopicResult }) {
  return (
    <div className="rounded-2xl border border-line bg-card p-5">
      <h3 className="text-xl font-semibold">{result.title}</h3>
      <p className="mt-1 text-sm text-muted">
        {statusLabel(result.category)} · {result.method || "not graded"} · {result.confidence === "approximate" ? "Approximate score" : result.confidence || "Skipped"}
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-4">
        <Mini label="Overall" value={formatPercent(result.overall)} />
        <Mini label="Concepts 50%" value={formatPercent(result.essentialCoverage)} />
        <Mini label="Facts 30%" value={formatPercent(result.factualCorrectness)} />
        <Mini label="Details 20%" value={formatPercent(result.supportingDetail)} />
      </div>
      <Lists covered={result.covered} missing={result.missing} incorrect={result.incorrect} />
      {result.revision ? <p className="mt-3 text-sm">{result.revision}</p> : null}
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <article>
          <h4 className="font-semibold">Your answer</h4>
          <p className="mt-1 whitespace-pre-wrap text-sm">{result.transcript || "Skipped"}</p>
        </article>
        <article>
          <h4 className="font-semibold">Reference note</h4>
          <p className="mt-1 whitespace-pre-wrap text-sm">{result.referenceText}</p>
        </article>
      </div>
    </div>
  );
}

function OralReport({ summary }: { summary: OralSummary }) {
  return (
    <div>
      <PageHeader title="Oral test result" lede="Scores compare concepts, not exact wording. Approximate scores are labeled." />
      <div className="grid gap-3 sm:grid-cols-3">
        <Mini label="Topics attempted" value={String(summary.attempted)} />
        <Mini label="Average recall" value={formatPercent(summary.averagePercent)} />
        <Mini label="Skipped" value={String(summary.skipped)} />
        <Mini label="Recalled successfully" value={String(summary.successful)} />
        <Mini label="Partially recalled" value={String(summary.partial)} />
        <Mini label="Needs revision" value={String(summary.needsRevision)} />
      </div>
      <p className="mt-3 text-sm text-muted">
        Well remembered is {summary.wellRememberedPercent}% or above. Developing starts at {summary.developingPercent}%.
      </p>
      <div className="mt-5">
        <Link className="rounded-xl bg-accent px-4 py-2 font-semibold text-accent-ink" to="/revision">Review weak topics</Link>
      </div>
      <div className="mt-6 space-y-4">
        {summary.topics.map((topic) => <Feedback key={topic.topicId} result={topic} />)}
      </div>
    </div>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line bg-paper p-3">
      <p className="text-xs text-muted">{label}</p>
      <p className="text-lg font-semibold">{value}</p>
    </div>
  );
}

function Lists({ covered, missing, incorrect }: { covered: string[]; missing: string[]; incorrect: string[] }) {
  return (
    <div className="mt-3 grid gap-3 md:grid-cols-3 text-sm">
      <PointList title="Correctly explained" items={covered} />
      <PointList title="Missing points" items={missing} />
      <PointList title="Incorrect statements" items={incorrect} />
    </div>
  );
}

function PointList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <h4 className="font-semibold">{title}</h4>
      {items.length === 0 ? <p className="text-muted">None</p> : <ul className="list-disc pl-4">{items.map((item) => <li key={item}>{item}</li>)}</ul>}
    </div>
  );
}

