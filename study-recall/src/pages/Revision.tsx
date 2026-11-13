import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorText } from "../api";
import { Notice, PageHeader, PrimaryButton, inputClass } from "../components/ui";
import { formatPercent, statusLabel } from "../format";
import { useStudent } from "../store";
import type { RevisionTopic } from "../types";

export function Revision() {
  const student = useStudent();
  const navigate = useNavigate();
  const [topics, setTopics] = useState<RevisionTopic[]>([]);
  const [topicLimit, setTopicLimit] = useState(1);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!student) return;
    api.revisionTopics(student.id).then((next) => {
      setTopics(next);
      setTopicLimit(next.filter((topic) => topic.status === "needs_revision").length || 1);
    }).catch((err) => setError(errorText(err)));
  }, [student]);

  async function start() {
    if (!student) return;
    try {
      const prompt = await api.startRevisionOral(student.id, topicLimit);
      navigate(`/oral/session/${prompt.sessionId}`, { state: { prompt } });
    } catch (err) {
      setError(errorText(err));
    }
  }

  if (!student) return <Notice>Create a student profile to track revision.</Notice>;

  const weak = topics.filter((topic) => topic.status === "needs_revision");

  return (
    <div>
      <PageHeader
        title="Topics needing revision"
        lede="These topics were skipped, scored below the developing line, or were marked from a written paper. Choose how many weak topics to practice."
        actions={
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm font-medium">
              How many topics
              <input
                className={`${inputClass} mt-1 w-28`}
                type="number"
                min={1}
                max={Math.max(1, weak.length)}
                value={Math.min(topicLimit, Math.max(1, weak.length))}
                disabled={weak.length === 0}
                onChange={(event) => setTopicLimit(Math.min(weak.length, Math.max(1, Number(event.target.value) || 1)))}
              />
            </label>
            <PrimaryButton disabled={weak.length === 0} onClick={() => void start()}>Practice weak topics</PrimaryButton>
          </div>
        }
      />
      {error ? <div className="mb-4"><Notice tone="error">{error}</Notice></div> : null}
      {topics.length === 0 ? <Notice>No revision list yet. Finish an oral or written test first.</Notice> : null}
      <ul className="space-y-3">
        {topics.map((topic) => (
          <li key={topic.topicId} className="rounded-2xl border border-line bg-card p-4">
            <Link className="text-lg font-semibold" to={`/topic/${topic.topicId}`}>{topic.title}</Link>
            <p className="text-sm text-muted">
              {topic.className} · {topic.bookTitle} · {topic.chapterTitle}
            </p>
            <p className="text-sm">
              {statusLabel(topic.status)}
              {topic.lastScore != null ? ` · ${formatPercent(topic.lastScore)}` : ""}
              {topic.lastSource ? ` · from ${topic.lastSource}` : ""}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
