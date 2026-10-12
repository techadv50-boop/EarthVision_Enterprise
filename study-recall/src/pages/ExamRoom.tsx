import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, errorText } from "../api";
import { Recorder, type RecorderHandle } from "../components/Recorder";
import { Notice, PageHeader, PrimaryButton, QuietButton, inputClass } from "../components/ui";
import { formatClock, questionLabel } from "../format";
import { originForRemaining, remainingMs } from "../timing";
import { bytesToBase64 } from "../wav";
import type { ExamView } from "../types";

export function ExamRoom() {
  const { examId = "" } = useParams();
  const navigate = useNavigate();
  const [view, setView] = useState<ExamView | null>(null);
  const [text, setText] = useState("");
  const [option, setOption] = useState<string | null>(null);
  const [left, setLeft] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const viewRef = useRef<ExamView | null>(null);
  const textRef = useRef("");
  const optionRef = useRef<string | null>(null);
  const recorderRef = useRef<RecorderHandle | null>(null);
  const expiring = useRef(false);
  const transcribing = useRef<string | null>(null);

  function accept(next: ExamView, resetAnswer: boolean) {
    viewRef.current = next;
    setView(next);
    if (resetAnswer) {
      const draft = next.question?.draftText ?? "";
      const selected = next.question?.draftOption ?? null;
      textRef.current = draft;
      optionRef.current = selected;
      setText(draft);
      setOption(selected);
    }
    if (next.status === "completed") navigate(`/exam/${examId}/results`);
    else if (next.status !== "ready" && next.status !== "in_progress") void maybeFinalize();
  }

  async function maybeFinalize() {
    const current = viewRef.current;
    if (!current || current.status === "ready" || current.status === "in_progress") return;
    if (current.pendingTranscription > 0 || transcribing.current) {
      setNotice("A recording is still being transcribed. The next question is not waiting. Results appear when transcription finishes or is marked for review.");
      return;
    }
    try {
      await api.finalizeExam(examId);
      navigate(`/exam/${examId}/results`);
    } catch (err) {
      const message = errorText(err);
      if (message.toLowerCase().includes("transcrib")) setNotice(message);
      else setError(message);
    }
  }

  useEffect(() => {
    let live = true;
    api.syncExam(examId, Date.now()).then((next) => {
      if (live) accept(next, true);
    }).catch((err) => {
      if (live) setError(errorText(err));
    });
    return () => {
      live = false;
    };
  }, [examId]);

  useEffect(() => {
    const current = view;
    const question = current?.question;
    if (!current || current.status !== "in_progress" || !question) return;
    const questionId = question.id;
    const generation = current.timerGeneration;
    const duration = current.durationMs;
    const origin = originForRemaining(performance.now(), duration, current.remainingMs);
    setLeft(remainingMs(origin, performance.now(), duration));
    let fired = false;
    const id = window.setInterval(() => {
      const leftMs = remainingMs(origin, performance.now(), duration);
      setLeft(leftMs);
      if (leftMs <= 0 && !fired) {
        fired = true;
        void expire(questionId, generation, duration);
      }
    }, 200);
    return () => window.clearInterval(id);
  }, [view?.question?.id, view?.status, view?.timerGeneration]);

  useEffect(() => {
    const question = view?.question;
    if (!question || view?.status !== "in_progress") return;
    const handle = window.setTimeout(() => {
      void api.saveExamDraft(examId, question.id, textRef.current, optionRef.current).catch(() => undefined);
    }, 800);
    return () => window.clearTimeout(handle);
  }, [examId, option, text, view?.question?.id, view?.status]);

  async function expire(questionId: string, generation: number, duration: number) {
    if (expiring.current) return;
    const current = viewRef.current;
    if (!current || current.question?.id !== questionId || current.timerGeneration !== generation) return;
    expiring.current = true;
    try {
      const wav = (await recorderRef.current?.stop()) ?? null;
      const spoken = current.question.questionType === "short" || current.question.questionType === "long";
      const needsTranscript = transcribing.current === questionId || (Boolean(wav) && spoken && !textRef.current.trim());
      if (needsTranscript) {
        const next = await api.submitExamAnswer(examId, questionId, textRef.current, optionRef.current, true, Date.now());
        accept(next, true);
        if (wav) void finishTranscript(questionId, wav);
      } else {
        await api.saveExamDraft(examId, questionId, textRef.current, optionRef.current).catch(() => undefined);
        const next = await api.syncExam(examId, Date.now(), generation, duration);
        accept(next, true);
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      expiring.current = false;
    }
  }

  async function finishTranscript(questionId: string, wav: Uint8Array) {
    transcribing.current = questionId;
    setNotice("Transcribing the previous answer on this computer. You can continue.");
    try {
      const outcome = await api.transcribe(bytesToBase64(wav), "auto");
      const failed = !outcome.ok || !outcome.text.trim();
      const next = await api.resolveTranscription(examId, questionId, failed ? "" : outcome.text, failed);
      if (!outcome.ok) setNotice(outcome.errorMessage);
      accept(next, viewRef.current?.question?.id !== next.question?.id);
    } catch (err) {
      try {
        const next = await api.resolveTranscription(examId, questionId, "", true);
        accept(next, viewRef.current?.question?.id !== next.question?.id);
      } catch {
        setError(errorText(err));
      }
    } finally {
      if (transcribing.current === questionId) transcribing.current = null;
      void maybeFinalize();
    }
  }

  async function transcribeNow() {
    const question = viewRef.current?.question;
    if (!question) return;
    const wav = await recorderRef.current?.stop();
    if (!wav) {
      setError("Record an answer first, or type it.");
      return;
    }
    transcribing.current = question.id;
    setNotice("Transcribing on this computer. The timer keeps running.");
    try {
      const outcome = await api.transcribe(bytesToBase64(wav), "auto");
      const still = viewRef.current?.question?.id === question.id && viewRef.current.status === "in_progress";
      if (still && outcome.ok) {
        const combined = textRef.current.trim() ? `${textRef.current.trim()}\n${outcome.text}` : outcome.text;
        textRef.current = combined;
        setText(combined);
        setNotice(outcome.warning || "Transcript added. You can edit it before submitting.");
      } else if (still) {
        setError(outcome.errorMessage);
      } else {
        const next = await api.resolveTranscription(examId, question.id, outcome.ok ? outcome.text : "", !outcome.ok);
        accept(next, false);
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      if (transcribing.current === question.id) transcribing.current = null;
      void maybeFinalize();
    }
  }

  async function submit() {
    const current = viewRef.current;
    const question = current?.question;
    if (!current || !question || busy || expiring.current) return;
    setBusy(true);
    try {
      const wav = (await recorderRef.current?.stop()) ?? null;
      const spoken = question.questionType === "short" || question.questionType === "long";
      const pending = transcribing.current === question.id || (Boolean(wav) && spoken && !textRef.current.trim());
      const next = await api.submitExamAnswer(examId, question.id, textRef.current, optionRef.current, pending, Date.now());
      accept(next, true);
      if (pending && wav) void finishTranscript(question.id, wav);
      setError("");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function begin() {
    setBusy(true);
    try {
      accept(await api.startExam(examId, Date.now()), true);
      setError("");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  if (!view && !error) return <p>Opening the examination…</p>;
  if (!view) return <Notice tone="error">{error}</Notice>;

  if (view.status === "ready") {
    return (
      <div>
        <PageHeader title={`${view.className} · ${view.bookTitle}`} lede="Read the instructions, then start. The timer for question 1 begins immediately." />
        {error ? <div className="mb-4"><Notice tone="error">{error}</Notice></div> : null}
        <article className="whitespace-pre-wrap rounded-2xl border border-line bg-card p-5">{view.instructions}</article>
        <p className="mt-3 text-sm text-muted">{view.weightingNote}</p>
        <details className="mt-3 text-sm text-muted">
          <summary>What happens if the app closes?</summary>
          <p className="mt-2">{view.recoveryPolicy}</p>
        </details>
        <div className="mt-5">
          <PrimaryButton disabled={busy} onClick={() => void begin()}>Start examination</PrimaryButton>
        </div>
      </div>
    );
  }

  const question = view.question;
  if (!question) {
    return (
      <div>
        <PageHeader title="Finishing the examination" lede={notice || "Answers are being collected."} />
        {error ? <div className="mb-4"><Notice tone="error">{error}</Notice></div> : null}
        <PrimaryButton onClick={() => void maybeFinalize()}>Calculate result</PrimaryButton>
      </div>
    );
  }

  const progress = view.totalQuestions === 0 ? 0 : ((question.position + 1) / view.totalQuestions) * 100;

  return (
    <div>
      <div className="mb-4 h-2 overflow-hidden rounded-full bg-line" aria-hidden="true">
        <div className="h-full bg-accent" style={{ width: `${progress}%` }} />
      </div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">
          Question {question.position + 1} of {view.totalQuestions} · {questionLabel(question.questionType)} · {question.maxMarks} marks
        </p>
        <p className="rounded-full bg-card px-4 py-1 text-lg font-semibold tabular-nums" aria-live="polite">
          {formatClock(left)}
        </p>
      </div>
      {error ? <div className="mb-4"><Notice tone="error">{error}</Notice></div> : null}
      {notice ? <div className="mb-4"><Notice tone="warn">{notice}</Notice></div> : null}
      <article className="rounded-2xl border border-line bg-card p-5">
        <h1 className="text-2xl font-semibold">{question.prompt}</h1>
        {question.questionType === "mcq" ? (
          <div className="mt-4 grid gap-2">
            {question.options.map((choice) => (
              <button
                key={choice.id}
                type="button"
                aria-pressed={option === choice.id}
                className={`rounded-xl border px-4 py-3 text-left ${option === choice.id ? "border-accent bg-accent/10" : "border-line"}`}
                onClick={() => {
                  optionRef.current = choice.id;
                  setOption(choice.id);
                }}
              >
                {choice.id}. {choice.text}
              </button>
            ))}
          </div>
        ) : null}
        {question.questionType === "fib" ? (
          <label className="mt-4 block text-sm font-medium">
            Your answer
            <input
              className={`${inputClass} mt-1`}
              value={text}
              onChange={(event) => {
                textRef.current = event.target.value;
                setText(event.target.value);
              }}
            />
          </label>
        ) : null}
        {question.questionType === "short" || question.questionType === "long" ? (
          <div className="mt-4 space-y-3">
            <Recorder ref={recorderRef} language="auto" showTranscribe={false} />
            <QuietButton onClick={() => void transcribeNow()}>Transcribe voice</QuietButton>
            <label className="block text-sm font-medium">
              Answer
              <textarea
                className={`${inputClass} mt-1 min-h-40`}
                value={text}
                onChange={(event) => {
                  textRef.current = event.target.value;
                  setText(event.target.value);
                }}
              />
            </label>
          </div>
        ) : null}
        <div className="mt-5">
          <PrimaryButton disabled={busy} onClick={() => void submit()}>
            {question.position + 1 === view.totalQuestions ? "Submit examination" : "Submit and go to the next question"}
          </PrimaryButton>
        </div>
      </article>
    </div>
  );
}
