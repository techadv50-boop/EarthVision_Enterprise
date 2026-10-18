import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, errorText } from "../api";
import { Crumbs, EmptyState, Notice, PageHeader, PrimaryButton, inputClass } from "../components/ui";
import { countNoun } from "../format";
import { useStudent } from "../store";
import type { BookSummary, ChapterSummary, ClassSummary, Proposal } from "../types";

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
    api.listChapters(bookId, false).then(setChapters).catch((err) => setError(errorText(err)));
  }, [bookId]);

  async function preview() {
    if (!student) return;
    setBusy(true);
    try {
      setProposal(await api.proposeExam(student.id, bookId, selected, difficulty));
      setError("");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function create(sizeId: string) {
    if (!student) return;
    setBusy(true);
    try {
      const created = await api.createExam(student.id, bookId, selected, difficulty, sizeId);
      navigate(`/exam/${created.examId}`);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  if (!student) return <Notice>Create a student profile before starting a written test.</Notice>;
  const className = classes.find((item) => item.id === classId)?.name;
  const bookTitle = books.find((item) => item.id === bookId)?.title;

  return (
    <div>
      <PageHeader
        title="Go for a Written Test"
        lede="Questions come only from the chapters you select. A full paper is 100 marks: 30% blanks, 40% multiple choice, and 30% short and long questions."
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
          <div className="mt-4">
            <PrimaryButton disabled={busy || selected.length === 0} onClick={() => void preview()}>
              {busy ? "Preparing…" : "Review paper sizes"}
            </PrimaryButton>
          </div>
          {proposal ? (
            <div className="mt-5 space-y-3">
              <Notice>{proposal.materialNote}</Notice>
              {proposal.difficultyNote ? <p className="text-sm text-muted">{proposal.difficultyNote}</p> : null}
              <p className="text-sm text-muted">
                Available from these notes: {proposal.fibAvailable} blanks, {proposal.mcqAvailable} multiple choice, {proposal.shortAvailable} short, {proposal.longAvailable} long.
              </p>
              {proposal.offers.map((offer) => (
                <article key={offer.sizeId} className="rounded-xl border border-line p-4">
                  <h3 className="text-lg font-semibold">{offer.title}</h3>
                  <p className="text-sm text-muted">
                    {offer.fibCount} blanks ({offer.sectionAMarks} marks, {offer.percentA}%) · {offer.mcqCount} multiple choice ({offer.sectionBMarks} marks, {offer.percentB}%) · {offer.shortCount} short and {offer.longCount} long ({offer.sectionCMarks} marks, {offer.percentC}%) · {offer.totalMarks} marks
                  </p>
                  {offer.roundingNote ? <p className="mt-1 text-sm">{offer.roundingNote}</p> : null}
                  <p className="mt-1 text-sm">{offer.feasible ? "This paper can be built from the selected notes." : offer.reason}</p>
                  <div className="mt-3">
                    <PrimaryButton disabled={!offer.feasible || busy} onClick={() => void create(offer.sizeId)}>
                      Use this paper
                    </PrimaryButton>
                  </div>
                </article>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
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
