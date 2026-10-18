import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, errorText, pickFile } from "../api";
import { Crumbs, EmptyState, Field, Modal, Notice, PageHeader, PrimaryButton, QuietButton, inputClass } from "../components/ui";
import { statusLabel } from "../format";
import { useStudent } from "../store";
import type { BookSummary, ChapterSummary, ClassSummary, ImportReport, TopicHit, TopicSummary } from "../types";

type Confirm = { kind: "class" | "book" | "chapter" | "topic"; id: string; name: string };

export function Study() {
  const { classId = "", bookId = "", chapterId = "" } = useParams();
  const student = useStudent();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<TopicHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [tick, setTick] = useState(0);
  const reload = () => setTick((value) => value + 1);

  async function search(event: FormEvent) {
    event.preventDefault();
    if (!student || query.trim().length < 2) {
      setHits([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    try {
      setHits(await api.searchTopics(student.id, query.trim()));
      setError("");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function remove() {
    if (!confirm) return;
    try {
      if (confirm.kind === "class") await api.softDeleteClass(confirm.id);
      if (confirm.kind === "book") await api.softDeleteBook(confirm.id);
      if (confirm.kind === "chapter") await api.softDeleteChapter(confirm.id);
      if (confirm.kind === "topic") await api.softDeleteTopic(confirm.id);
      setConfirm(null);
      reload();
    } catch (err) {
      setError(errorText(err));
      setConfirm(null);
    }
  }

  if (!student) {
    return <Notice>Create a student profile in Settings before adding study material.</Notice>;
  }

  return (
    <div>
      <PageHeader
        title="My Classes"
        lede="Build Class, then Book, then Chapter, then Topic, or import a Word file that is already arranged chapter by chapter. Your notes are the only source used for tests."
      />
      <form className="mb-4 flex gap-2" onSubmit={(event) => void search(event)}>
        <input
          className={inputClass}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search topics"
          aria-label="Search topics"
        />
        <PrimaryButton type="submit">Search</PrimaryButton>
      </form>
      <label className="mb-4 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={includeArchived} onChange={(event) => setIncludeArchived(event.target.checked)} />
        Show archived items
      </label>
      {error ? <div className="mb-4"><Notice tone="error">{error}</Notice></div> : null}
      {searching ? (
        <SearchResults hits={hits} onClear={() => { setSearching(false); setHits([]); }} />
      ) : (
        <Level
          studentId={student.id}
          classId={classId}
          bookId={bookId}
          chapterId={chapterId}
          includeArchived={includeArchived}
          tick={tick}
          onError={setError}
          onChange={reload}
          onDelete={setConfirm}
        />
      )}
      {confirm ? (
        <Modal
          title={`Move “${confirm.name}” to Recently deleted?`}
          body="You can restore it from Settings. Permanent removal is a separate step and asks you to type DELETE."
          confirmLabel="Move to Recently deleted"
          onClose={() => setConfirm(null)}
          onConfirm={() => void remove()}
        />
      ) : null}
    </div>
  );
}

function SearchResults({ hits, onClear }: { hits: TopicHit[]; onClear: () => void }) {
  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-xl font-semibold">Search results</h2>
        <QuietButton onClick={onClear}>Back to classes</QuietButton>
      </div>
      {hits.length === 0 ? <EmptyState title="No matching topics" body="Try another word from the topic title." /> : null}
      <ul className="space-y-2">
        {hits.map((hit) => (
          <li key={hit.topicId} className="rounded-2xl border border-line bg-card p-4">
            <Link className="text-lg font-semibold underline-offset-2 hover:underline" to={`/topic/${hit.topicId}`}>
              {hit.title}
            </Link>
            <p className="text-sm text-muted">
              {hit.className} / {hit.bookTitle} / {hit.chapterTitle} · {statusLabel(hit.revisionStatus)}
              {hit.hasReference ? " · notes saved" : " · no notes yet"}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Level(props: {
  studentId: string;
  classId: string;
  bookId: string;
  chapterId: string;
  includeArchived: boolean;
  tick: number;
  onError: (message: string) => void;
  onChange: () => void;
  onDelete: (item: Confirm) => void;
}) {
  if (props.chapterId) return <Topics {...props} />;
  if (props.bookId) return <Chapters {...props} />;
  if (props.classId) return <Books {...props} />;
  return <Classes {...props} />;
}

function Classes(props: {
  studentId: string;
  includeArchived: boolean;
  tick: number;
  onError: (message: string) => void;
  onChange: () => void;
  onDelete: (item: Confirm) => void;
}) {
  const [items, setItems] = useState<ClassSummary[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  useEffect(() => {
    api.listClasses(props.studentId, props.includeArchived).then(setItems).catch((err) => props.onError(errorText(err)));
  }, [props.studentId, props.includeArchived, props.tick]);

  async function add(event: FormEvent) {
    event.preventDefault();
    try {
      await api.createClass(props.studentId, name, description);
      setName("");
      setDescription("");
      props.onChange();
    } catch (err) {
      props.onError(errorText(err));
    }
  }

  return (
    <section>
      <Crumbs items={[{ label: "Classes" }]} />
      {items.length === 0 ? (
        <EmptyState title="No classes yet" body="Add a class such as Class 10. You can rename, reorder, archive, or delete it later." />
      ) : null}
      <ul className="mt-4 space-y-3">
        {items.map((item, index) => (
          <li key={item.id} className="rounded-2xl border border-line bg-card p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <Link className="text-xl font-semibold" to={`/study/${item.id}`}>{item.name}</Link>
                {item.description ? <p className="text-muted">{item.description}</p> : null}
                <p className="mt-1 text-sm text-muted">
                  {item.bookCount} books · {item.topicCount} topics · {item.studiedTopicCount} with notes · {item.testedTopicCount} tested
                  {item.archived ? " · archived" : ""}
                </p>
              </div>
              <RowActions
                onUp={() => void reorder(items.map((row) => row.id), index, -1, (ids) => api.reorderClasses(props.studentId, ids), props)}
                onDown={() => void reorder(items.map((row) => row.id), index, 1, (ids) => api.reorderClasses(props.studentId, ids), props)}
                onArchive={() => void api.setClassArchived(item.id, !item.archived).then(props.onChange).catch((err) => props.onError(errorText(err)))}
                archived={item.archived}
                onDelete={() => props.onDelete({ kind: "class", id: item.id, name: item.name })}
                onRename={(next) => void api.updateClass(item.id, next, item.description).then(props.onChange).catch((err) => props.onError(errorText(err)))}
              />
            </div>
          </li>
        ))}
      </ul>
      <form className="mt-6 grid gap-3 rounded-2xl border border-line bg-card p-4 sm:grid-cols-[1fr_1fr_auto]" onSubmit={(event) => void add(event)}>
        <Field label="New class">
          <input className={inputClass} value={name} onChange={(event) => setName(event.target.value)} required />
        </Field>
        <Field label="Description (optional)">
          <input className={inputClass} value={description} onChange={(event) => setDescription(event.target.value)} />
        </Field>
        <div className="self-end"><PrimaryButton type="submit">Add class</PrimaryButton></div>
      </form>
    </section>
  );
}

function Books(props: {
  studentId: string;
  classId: string;
  includeArchived: boolean;
  tick: number;
  onError: (message: string) => void;
  onChange: () => void;
  onDelete: (item: Confirm) => void;
}) {
  const [items, setItems] = useState<BookSummary[]>([]);
  const [className, setClassName] = useState("Class");
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("en");

  useEffect(() => {
    Promise.all([
      api.listBooks(props.classId, props.includeArchived),
      api.listClasses(props.studentId, true),
    ]).then(([books, classes]) => {
      setItems(books);
      setClassName(classes.find((item) => item.id === props.classId)?.name ?? "Class");
    }).catch((err) => props.onError(errorText(err)));
  }, [props.classId, props.includeArchived, props.tick, props.studentId]);

  async function add(event: FormEvent) {
    event.preventDefault();
    try {
      await api.createBook(props.classId, title, language);
      setTitle("");
      props.onChange();
    } catch (err) {
      props.onError(errorText(err));
    }
  }

  return (
    <section>
      <Crumbs items={[{ label: "Classes", to: "/study" }, { label: className }]} />
      {items.length === 0 ? (
        <EmptyState title="No books in this class" body="Add a book such as Biology. You can add as many books as you need." />
      ) : null}
      <ul className="mt-4 space-y-3">
        {items.map((item, index) => (
          <li key={item.id} className="rounded-2xl border border-line bg-card p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <Link className="text-xl font-semibold" to={`/study/${props.classId}/${item.id}`}>{item.title}</Link>
                <p className="mt-1 text-sm text-muted">
                  {item.language === "ur" ? "Urdu" : "English"} · {item.chapterCount} chapters · {item.topicCount} topics
                  {item.archived ? " · archived" : ""}
                </p>
              </div>
              <RowActions
                onUp={() => void reorder(items.map((row) => row.id), index, -1, (ids) => api.reorderBooks(props.classId, ids), props)}
                onDown={() => void reorder(items.map((row) => row.id), index, 1, (ids) => api.reorderBooks(props.classId, ids), props)}
                onArchive={() => void api.setBookArchived(item.id, !item.archived).then(props.onChange).catch((err) => props.onError(errorText(err)))}
                archived={item.archived}
                onDelete={() => props.onDelete({ kind: "book", id: item.id, name: item.title })}
                onRename={(next) => void api.updateBook(item.id, next, item.language).then(props.onChange).catch((err) => props.onError(errorText(err)))}
              />
            </div>
          </li>
        ))}
      </ul>
      <form className="mt-6 grid gap-3 rounded-2xl border border-line bg-card p-4 sm:grid-cols-[1fr_180px_auto]" onSubmit={(event) => void add(event)}>
        <Field label="New book">
          <input className={inputClass} value={title} onChange={(event) => setTitle(event.target.value)} required />
        </Field>
        <Field label="Language">
          <select className={inputClass} value={language} onChange={(event) => setLanguage(event.target.value)}>
            <option value="en">English</option>
            <option value="ur">Urdu</option>
          </select>
        </Field>
        <div className="self-end"><PrimaryButton type="submit">Add book</PrimaryButton></div>
      </form>
    </section>
  );
}

function Chapters(props: {
  classId: string;
  bookId: string;
  includeArchived: boolean;
  tick: number;
  onError: (message: string) => void;
  onChange: () => void;
  onDelete: (item: Confirm) => void;
  studentId: string;
}) {
  const [items, setItems] = useState<ChapterSummary[]>([]);
  const [bookTitle, setBookTitle] = useState("Book");
  const [className, setClassName] = useState("Class");
  const [title, setTitle] = useState("");
  const [importing, setImporting] = useState(false);
  const [imported, setImported] = useState<ImportReport | null>(null);

  useEffect(() => {
    Promise.all([
      api.listChapters(props.bookId, props.includeArchived),
      api.listBooks(props.classId, true),
      api.listClasses(props.studentId, true),
    ]).then(([chapters, books, classes]) => {
      setItems(chapters);
      setBookTitle(books.find((item) => item.id === props.bookId)?.title ?? "Book");
      setClassName(classes.find((item) => item.id === props.classId)?.name ?? "Class");
    }).catch((err) => props.onError(errorText(err)));
  }, [props.bookId, props.classId, props.includeArchived, props.studentId, props.tick]);

  async function add(event: FormEvent) {
    event.preventDefault();
    try {
      await api.createChapter(props.bookId, title);
      setTitle("");
      props.onChange();
    } catch (err) {
      props.onError(errorText(err));
    }
  }

  async function importWord() {
    const path = await pickFile([{ name: "Word", extensions: ["docx"] }]);
    if (!path) return;
    setImporting(true);
    try {
      const report = await api.importWord(props.bookId, path);
      setImported(report);
      props.onChange();
      props.onError("");
    } catch (err) {
      props.onError(errorText(err));
    } finally {
      setImporting(false);
    }
  }

  return (
    <section>
      <Crumbs items={[{ label: "Classes", to: "/study" }, { label: className, to: `/study/${props.classId}` }, { label: bookTitle }]} />
      <section className="mt-4 rounded-2xl border border-line bg-card p-4">
        <h2 className="text-lg font-semibold">Import a Word file</h2>
        <p className="mt-1 text-sm text-muted">
          If the notes are already separated chapter by chapter, choose the .docx file. Start each chapter with “Chapter 1: …” or Word Heading 1, and each topic with “Topic: …” or Heading 2. The file stays on this computer and is placed into this book.
        </p>
        <div className="mt-3">
          <PrimaryButton disabled={importing} onClick={() => void importWord()}>
            {importing ? "Importing…" : "Choose Word file"}
          </PrimaryButton>
        </div>
        {imported ? (
          <div className="mt-3 text-sm">
            <p>
              {imported.chaptersCreated} chapters added, {imported.chaptersReused} already present, {imported.topicsCreated} topics added, {imported.notesSaved} notes saved.
              {imported.notesLeftUnchanged > 0 ? ` ${imported.notesLeftUnchanged} topics already had notes and were left unchanged.` : ""}
            </p>
            {imported.warnings.map((warning, index) => <p key={`${index}-${warning}`} className="mt-1 text-muted">{warning}</p>)}
          </div>
        ) : null}
      </section>
      {items.length === 0 ? (
        <EmptyState title="No chapters have been added to this book." body="Add the first chapter. Topics and notes belong inside a chapter." action={<span className="text-sm text-muted">Use the form below.</span>} />
      ) : null}
      <ul className="mt-4 space-y-3">
        {items.map((item, index) => (
          <li key={item.id} className="rounded-2xl border border-line bg-card p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <Link className="text-xl font-semibold" to={`/study/${props.classId}/${props.bookId}/${item.id}`}>{item.title}</Link>
                <p className="mt-1 text-sm text-muted">
                  {item.topicCount} topics · {item.studiedTopicCount} with notes · {item.testedTopicCount} tested
                  {item.archived ? " · archived" : ""}
                </p>
              </div>
              <RowActions
                onUp={() => void reorder(items.map((row) => row.id), index, -1, (ids) => api.reorderChapters(props.bookId, ids), props)}
                onDown={() => void reorder(items.map((row) => row.id), index, 1, (ids) => api.reorderChapters(props.bookId, ids), props)}
                onArchive={() => void api.setChapterArchived(item.id, !item.archived).then(props.onChange).catch((err) => props.onError(errorText(err)))}
                archived={item.archived}
                onDelete={() => props.onDelete({ kind: "chapter", id: item.id, name: item.title })}
                onRename={(next) => void api.updateChapter(item.id, next).then(props.onChange).catch((err) => props.onError(errorText(err)))}
              />
            </div>
          </li>
        ))}
      </ul>
      <form className="mt-6 flex flex-wrap items-end gap-3 rounded-2xl border border-line bg-card p-4" onSubmit={(event) => void add(event)}>
        <div className="min-w-[240px] flex-1">
          <Field label="Add chapter">
            <input className={inputClass} value={title} onChange={(event) => setTitle(event.target.value)} required />
          </Field>
        </div>
        <PrimaryButton type="submit">Add chapter</PrimaryButton>
      </form>
    </section>
  );
}

function Topics(props: {
  classId: string;
  bookId: string;
  chapterId: string;
  includeArchived: boolean;
  tick: number;
  onError: (message: string) => void;
  onChange: () => void;
  onDelete: (item: Confirm) => void;
  studentId: string;
}) {
  const [items, setItems] = useState<TopicSummary[]>([]);
  const [destinations, setDestinations] = useState<{ id: string; label: string }[]>([]);
  const [names, setNames] = useState({ className: "Class", book: "Book", chapter: "Chapter" });
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("en");
  const [moveTarget, setMoveTarget] = useState<Record<string, string>>({});

  useEffect(() => {
    let live = true;
    Promise.all([
      api.listTopics(props.chapterId, props.includeArchived),
      api.listBooks(props.classId, false),
      api.listClasses(props.studentId, true),
    ]).then(async ([topics, books, classes]) => {
      const chapterGroups = await Promise.all(books.map(async (book) => {
        const chapters = await api.listChapters(book.id, false);
        return chapters.map((chapter) => ({ id: chapter.id, label: `${book.title} / ${chapter.title}`, title: chapter.title, bookId: book.id }));
      }));
      if (!live) return;
      const flat = chapterGroups.flat();
      setItems(topics);
      setDestinations(flat.filter((chapter) => chapter.id !== props.chapterId).map((chapter) => ({ id: chapter.id, label: chapter.label })));
      setNames({
        className: classes.find((item) => item.id === props.classId)?.name ?? "Class",
        book: books.find((item) => item.id === props.bookId)?.title ?? "Book",
        chapter: flat.find((item) => item.id === props.chapterId)?.title ?? "Chapter",
      });
    }).catch((err) => {
      if (live) props.onError(errorText(err));
    });
    return () => {
      live = false;
    };
  }, [props.bookId, props.chapterId, props.classId, props.includeArchived, props.studentId, props.tick]);

  async function add(event: FormEvent) {
    event.preventDefault();
    try {
      await api.createTopic(props.chapterId, title, language);
      setTitle("");
      props.onChange();
    } catch (err) {
      props.onError(errorText(err));
    }
  }

  return (
    <section>
      <Crumbs
        items={[
          { label: "Classes", to: "/study" },
          { label: names.className, to: `/study/${props.classId}` },
          { label: names.book, to: `/study/${props.classId}/${props.bookId}` },
          { label: names.chapter },
        ]}
      />
      {items.length === 0 ? (
        <EmptyState title="No topics in this chapter" body="Add a topic, then open it to type or record the reference notes." />
      ) : null}
      <ul className="mt-4 space-y-3">
        {items.map((item, index) => (
          <li key={item.id} className="rounded-2xl border border-line bg-card p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <Link className="text-xl font-semibold" to={`/topic/${item.id}`}>{item.title}</Link>
                <p className="mt-1 text-sm text-muted">
                  {item.language === "ur" ? "Urdu" : "English"} · {item.hasReference ? "notes saved" : "no notes yet"} · {statusLabel(item.revisionStatus)}
                  {item.lastScore != null ? ` · last score ${Math.round(item.lastScore)}%` : ""}
                  {item.archived ? " · archived" : ""}
                </p>
              </div>
              <RowActions
                onUp={() => void reorder(items.map((row) => row.id), index, -1, (ids) => api.reorderTopics(props.chapterId, ids), props)}
                onDown={() => void reorder(items.map((row) => row.id), index, 1, (ids) => api.reorderTopics(props.chapterId, ids), props)}
                onArchive={() => void api.setTopicArchived(item.id, !item.archived).then(props.onChange).catch((err) => props.onError(errorText(err)))}
                archived={item.archived}
                onDelete={() => props.onDelete({ kind: "topic", id: item.id, name: item.title })}
                onRename={(next) => void api.updateTopic(item.id, next, item.language).then(props.onChange).catch((err) => props.onError(errorText(err)))}
              />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <label className="text-sm">
                Move to
                <select
                  className="ml-2 rounded-lg border border-line bg-paper px-2 py-1"
                  value={moveTarget[item.id] ?? ""}
                  onChange={(event) => setMoveTarget({ ...moveTarget, [item.id]: event.target.value })}
                >
                  <option value="">Choose a chapter</option>
                  {destinations.map((chapter) => (
                    <option key={chapter.id} value={chapter.id}>{chapter.label}</option>
                  ))}
                </select>
              </label>
              <QuietButton
                disabled={!moveTarget[item.id]}
                onClick={() => void api.moveTopic(item.id, moveTarget[item.id]).then(props.onChange).catch((err) => props.onError(errorText(err)))}
              >
                Move topic
              </QuietButton>
            </div>
          </li>
        ))}
      </ul>
      <form className="mt-6 grid gap-3 rounded-2xl border border-line bg-card p-4 sm:grid-cols-[1fr_180px_auto]" onSubmit={(event) => void add(event)}>
        <Field label="New topic">
          <input className={inputClass} value={title} onChange={(event) => setTitle(event.target.value)} required />
        </Field>
        <Field label="Language">
          <select className={inputClass} value={language} onChange={(event) => setLanguage(event.target.value)}>
            <option value="en">English</option>
            <option value="ur">Urdu</option>
          </select>
        </Field>
        <div className="self-end"><PrimaryButton type="submit">Add topic</PrimaryButton></div>
      </form>
    </section>
  );
}

function RowActions(props: {
  onUp: () => void;
  onDown: () => void;
  onArchive: () => void;
  archived: boolean;
  onDelete: () => void;
  onRename: (name: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  return (
    <div className="flex flex-wrap gap-2">
      <QuietButton onClick={props.onUp}>Up</QuietButton>
      <QuietButton onClick={props.onDown}>Down</QuietButton>
      <QuietButton onClick={props.onArchive}>{props.archived ? "Unarchive" : "Archive"}</QuietButton>
      {editing ? (
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            props.onRename(name);
            setEditing(false);
          }}
        >
          <input className="rounded-lg border border-line bg-paper px-2 py-1" value={name} onChange={(event) => setName(event.target.value)} required aria-label="New name" />
          <QuietButton type="submit">Save name</QuietButton>
        </form>
      ) : (
        <QuietButton onClick={() => setEditing(true)}>Rename</QuietButton>
      )}
      <QuietButton onClick={props.onDelete}>Delete</QuietButton>
    </div>
  );
}

async function reorder(
  ids: string[],
  index: number,
  direction: -1 | 1,
  save: (ids: string[]) => Promise<void>,
  props: { onChange: () => void; onError: (message: string) => void },
) {
  const next = index + direction;
  if (next < 0 || next >= ids.length) return;
  const copy = [...ids];
  const [item] = copy.splice(index, 1);
  copy.splice(next, 0, item);
  try {
    await save(copy);
    props.onChange();
  } catch (err) {
    props.onError(errorText(err));
  }
}
