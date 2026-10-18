import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, errorText } from "../api";
import { Recorder } from "../components/Recorder";
import { SpeakButton } from "../components/SpeakButton";
import { Crumbs, Field, Notice, PageHeader, PrimaryButton, QuietButton, inputClass } from "../components/ui";
import { CONCEPT_KINDS, statusLabel } from "../format";
import type { Concept, TopicDetail } from "../types";

export function TopicEditor() {
  const { topicId = "" } = useParams();
  const [topic, setTopic] = useState<TopicDetail | null>(null);
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("en");
  const [text, setText] = useState("");
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [offerDraft, setOfferDraft] = useState(false);
  const dirty = useRef(false);
  const direction = language === "ur" ? "rtl" : "ltr";

  useEffect(() => {
    let live = true;
    api.getTopic(topicId).then((loaded) => {
      if (!live) return;
      setTopic(loaded);
      setTitle(loaded.title);
      setLanguage(loaded.language);
      setText(loaded.referenceText);
      setConcepts(loaded.concepts);
      setOfferDraft(loaded.hasDraft);
      dirty.current = false;
    }).catch((err) => {
      if (live) setError(errorText(err));
    });
    return () => {
      live = false;
    };
  }, [topicId]);

  useEffect(() => {
    if (!topic || !dirty.current || !title.trim()) return;
    const handle = window.setTimeout(() => {
      const usable = concepts.filter((concept) => concept.content.trim());
      api.saveTopicDraft(topic.id, title, language, text, usable)
        .then(() => setStatus("Draft saved on this computer."))
        .catch((err) => setError(errorText(err)));
    }, 1200);
    return () => window.clearTimeout(handle);
  }, [concepts, language, text, title, topic]);

  function edit(next: () => void) {
    dirty.current = true;
    next();
  }

  function updateConcept(index: number, patch: Partial<Concept>) {
    edit(() => setConcepts(concepts.map((concept, item) => (item === index ? { ...concept, ...patch } : concept))));
  }

  async function save() {
    if (!topic) return;
    try {
      const usable = concepts.filter((concept) => concept.content.trim());
      const saved = await api.saveTopic(topic.id, title, language, text, usable);
      setTopic(saved);
      setConcepts(saved.concepts);
      dirty.current = false;
      setOfferDraft(false);
      setStatus("Topic saved. Tests will use this note.");
      setError("");
    } catch (err) {
      setError(errorText(err));
    }
  }

  if (!topic && !error) return <p>Loading topic…</p>;
  if (!topic) return <Notice tone="error">{error}</Notice>;

  return (
    <div>
      <Crumbs
        items={[
          { label: "Classes", to: "/study" },
          { label: topic.className, to: `/study/${topic.classId}` },
          { label: topic.bookTitle, to: `/study/${topic.classId}/${topic.bookId}` },
          { label: topic.chapterTitle, to: `/study/${topic.classId}/${topic.bookId}/${topic.chapterId}` },
          { label: topic.title },
        ]}
      />
      <PageHeader
        title={title || "Topic"}
        lede={`${topic.className} · ${topic.bookTitle} · ${topic.chapterTitle}. ${statusLabel(topic.revisionStatus)}.`}
      />
      {offerDraft ? (
        <div className="mb-4">
          <Notice tone="warn">
            An unsaved draft is stored for this topic.
            <span className="ml-2 inline-flex gap-2">
              <QuietButton
                onClick={() => {
                  setText(topic.draftText);
                  setConcepts(topic.draftConcepts.length ? topic.draftConcepts : concepts);
                  setOfferDraft(false);
                  dirty.current = true;
                }}
              >
                Use draft
              </QuietButton>
              <QuietButton onClick={() => setOfferDraft(false)}>Keep saved note</QuietButton>
            </span>
          </Notice>
        </div>
      ) : null}
      {error ? <div className="mb-4"><Notice tone="error">{error}</Notice></div> : null}
      {status ? <div className="mb-4"><Notice tone="ok">{status}</Notice></div> : null}
      <div className="grid gap-4">
        <div className="grid gap-4 sm:grid-cols-[1fr_180px]">
          <Field label="Topic title">
            <input className={inputClass} value={title} onChange={(event) => edit(() => setTitle(event.target.value))} />
          </Field>
          <Field label="Language">
            <select className={inputClass} value={language} onChange={(event) => edit(() => setLanguage(event.target.value))}>
              <option value="en">English</option>
              <option value="ur">Urdu</option>
            </select>
          </Field>
        </div>
        <Field label="Reference information">
          <textarea
            className={`${inputClass} min-h-56`}
            dir={direction}
            lang={language}
            value={text}
            onChange={(event) => edit(() => setText(event.target.value))}
            placeholder="Type or paste the notes you want to be tested on."
          />
        </Field>
        <SpeakButton text={text || title} language={language} />
        <Recorder
          language={language}
          onTranscript={(transcript) => {
            edit(() => setText((current) => (current.trim() ? `${current.trim()}\n${transcript}` : transcript)));
            setStatus("Transcript added. Correct any recognition mistakes, then save the topic.");
          }}
        />
        <section className="rounded-2xl border border-line bg-card p-4">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">Extra reference items</h2>
            <QuietButton
              onClick={() => edit(() => setConcepts([...concepts, { kind: "fact", label: "", content: "", aliases: "" }]))}
            >
              Add item
            </QuietButton>
          </div>
          <p className="mt-1 text-sm text-muted">Definitions, facts, keywords, formulas, examples, and expected answer points. Leave an item blank to skip it.</p>
          <div className="mt-4 space-y-3">
            {concepts.map((concept, index) => (
              <div key={index} className="grid gap-2 rounded-xl border border-line p-3 md:grid-cols-[180px_1fr]">
                <select className={inputClass} value={concept.kind} onChange={(event) => updateConcept(index, { kind: event.target.value })}>
                  {CONCEPT_KINDS.map((kind) => (
                    <option key={kind.id} value={kind.id}>{kind.label}</option>
                  ))}
                </select>
                <input className={inputClass} dir={direction} value={concept.label} placeholder="Short label" onChange={(event) => updateConcept(index, { label: event.target.value })} />
                <textarea className={`${inputClass} md:col-span-2`} dir={direction} value={concept.content} placeholder="The exact note to test" onChange={(event) => updateConcept(index, { content: event.target.value })} />
                <input className={`${inputClass} md:col-span-2`} value={concept.aliases} placeholder="Optional aliases, separated by commas" onChange={(event) => updateConcept(index, { aliases: event.target.value })} />
                <QuietButton onClick={() => edit(() => setConcepts(concepts.filter((_, item) => item !== index)))}>Remove</QuietButton>
              </div>
            ))}
          </div>
        </section>
        <div className="flex flex-wrap items-center gap-3">
          <PrimaryButton onClick={() => void save()}>Save topic</PrimaryButton>
          <Link className="text-sm underline" to={`/study/${topic.classId}/${topic.bookId}/${topic.chapterId}`}>Back to chapter</Link>
        </div>
      </div>
    </div>
  );
}
