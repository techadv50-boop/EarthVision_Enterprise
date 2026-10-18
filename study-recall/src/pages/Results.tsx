import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, errorText, pickSavePath } from "../api";
import { Notice, PageHeader, PrimaryButton, QuietButton } from "../components/ui";
import { formatClock, formatMarks, formatPercent, questionLabel } from "../format";
import type { ExamResult } from "../types";

export function Results() {
  const { examId = "" } = useParams();
  const [result, setResult] = useState<ExamResult | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    api.getExamResult(examId).then(setResult).catch((err) => setError(errorText(err)));
  }, [examId]);

  async function exportHtml() {
    const path = await pickSavePath(`study-recall-${examId}.html`, [{ name: "HTML", extensions: ["html"] }]);
    if (!path) return;
    try {
      await api.saveExamHtml(examId, path);
      setMessage(`Saved ${path}. Open it in a browser and choose Print, then Save as PDF.`);
    } catch (err) {
      setError(errorText(err));
    }
  }

  if (!result && !error) return <p>Loading the result…</p>;
  if (!result) return <Notice tone="error">{error}</Notice>;

  return (
    <div>
      <div className="no-print mb-4 flex flex-wrap gap-2">
        <PrimaryButton onClick={() => window.print()}>Print or save as PDF</PrimaryButton>
        <QuietButton onClick={() => void exportHtml()}>Export HTML</QuietButton>
      </div>
      {error ? <div className="no-print mb-4"><Notice tone="error">{error}</Notice></div> : null}
      {message ? <div className="no-print mb-4"><Notice tone="ok">{message}</Notice></div> : null}
      <PageHeader title="Examination result" lede={result.gradingNote} />
      <section className="print-card rounded-2xl border border-line bg-card p-5">
        <h2 className="text-2xl font-semibold">{result.studentName}</h2>
        <p>{result.className} · {result.bookTitle}</p>
        <p className="text-sm text-muted">Chapters: {result.chapterTitles.join(", ") || "—"}</p>
        <p className="text-sm text-muted">Date: {result.takenAt}</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-4">
          <Stat label="Obtained" value={`${formatMarks(result.obtainedMarks)} / ${result.maxMarks}`} />
          <Stat label="Percentage" value={formatPercent(result.percentage)} />
          <Stat label="Time taken" value={formatClock(result.timeTakenMs)} />
          <Stat label="Correct / incorrect / unanswered" value={`${result.correctCount} / ${result.incorrectCount} / ${result.unansweredCount}`} />
        </div>
        {result.reviewCount > 0 ? <p className="mt-3 text-sm">Answers needing review: {result.reviewCount}. Those marks were not invented.</p> : null}
        {result.partialCount > 0 ? <p className="text-sm">Partial answers: {result.partialCount}.</p> : null}
        <p className="mt-3 text-sm text-muted">{result.weightingNote}</p>
      </section>
      <section className="mt-6 grid gap-3 md:grid-cols-2">
        {result.sections.map((section) => (
          <article key={section.name} className="print-card rounded-2xl border border-line bg-card p-4">
            <h3 className="font-semibold">{section.name}</h3>
            <p>{formatMarks(section.awarded)} / {section.maxMarks}</p>
            <p className="text-sm text-muted">
              Correct {section.correct} · partial {section.partial} · incorrect {section.incorrect} · unanswered {section.unanswered} · review {section.review}
            </p>
          </article>
        ))}
      </section>
      <section className="mt-6 space-y-4">
        {result.questions.map((question) => (
          <article key={question.position} className="print-card rounded-2xl border border-line bg-card p-5">
            <p className="text-sm text-muted">Question {question.position + 1} · {questionLabel(question.questionType)} · {formatMarks(question.awarded)} / {question.maxMarks}</p>
            <h3 className="mt-1 text-lg font-semibold">{question.prompt}</h3>
            {question.options.length > 0 ? (
              <ul className="mt-2 text-sm">
                {question.options.map((option) => <li key={option.id}>{option.id}. {option.text}</li>)}
              </ul>
            ) : null}
            <p className="mt-3 text-sm"><span className="font-semibold">Your answer: </span>{question.studentAnswer || "Unanswered"}</p>
            <p className="text-sm"><span className="font-semibold">Expected: </span>{question.correctAnswer}</p>
            <p className="mt-2 text-sm">{question.explanation}</p>
            <p className="mt-1 text-xs text-muted">{question.method} · {question.confidence}</p>
            {question.sourceTopicId ? (
              <Link className="mt-2 inline-block text-sm underline" to={`/topic/${question.sourceTopicId}`}>
                Revise {question.topicTitle || "the source topic"}
              </Link>
            ) : null}
          </article>
        ))}
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted">{label}</p>
      <p className="text-lg font-semibold">{value}</p>
    </div>
  );
}
