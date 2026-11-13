import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorText } from "../api";
import { PlanModeSwitch, TimeChoices, type PlanMode } from "../components/TestChoice";
import { Notice, PageHeader, PrimaryButton, inputClass } from "../components/ui";
import { countNoun, formatDuration, formatPercent, statusLabel } from "../format";
import { ORAL_TOPIC_SECONDS, countWithinTime } from "../testPlan";
import { useStudent } from "../store";
import type { RevisionTopic } from "../types";

export function Revision() {
  const student = useStudent();
  const navigate = useNavigate();
  const [topics, setTopics] = useState<RevisionTopic[]>([]);
  const [topicLimit, setTopicLimit] = useState(0);
  const [mode, setMode] = useState<PlanMode>("time");
  const [minutes, setMinutes] = useState(30);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!student) return;
    api.revisionTopics(student.id).then((next) => {
      setTopics(next);
      const ready = next.filter((topic) => topic.status === "needs_revision").length;
      setMode("time");
      setMinutes(30);
      setTopicLimit(countWithinTime(30, ready, ORAL_TOPIC_SECONDS));
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
        lede="These topics were skipped, scored below the developing line, or were marked from a written paper. Go by time, or set how many weak topics to practice."
      />
      {weak.length > 0 ? (
        <section className="mb-6 space-y-4 rounded-2xl border border-line bg-card p-5">
          <PlanModeSwitch
            mode={mode}
            timeBody="Choose 15 minutes, 30 minutes, 45 minutes, 1 hour, 2 hours, or 3 hours. The number of weak topics that fit is shown for that period."
            countTitle="Go by number of topics"
            countBody="Set how many weak topics you want to practice. The time is calculated from those topics."
            onChange={(next) => {
              setMode(next);
              if (next === "time") setTopicLimit(countWithinTime(minutes, weak.length, ORAL_TOPIC_SECONDS));
            }}
          />
          {mode === "time" ? (
            <TimeChoices
              minutes={minutes}
              label="Time for revision practice"
              onChange={(next) => {
                setMinutes(next);
                setTopicLimit(countWithinTime(next, weak.length, ORAL_TOPIC_SECONDS));
              }}
            />
          ) : (
            <label className="block max-w-xs text-sm font-medium">
              How many topics
              <input
                className={`${inputClass} mt-1`}
                type="number"
                min={1}
                max={weak.length}
                value={Math.max(1, topicLimit)}
                onChange={(event) => setTopicLimit(Math.min(weak.length, Math.max(1, Number(event.target.value) || 1)))}
              />
            </label>
          )}
          <p className="text-sm">{countNoun(topicLimit, "topic")} · time for this practice: {formatDuration(topicLimit * ORAL_TOPIC_SECONDS)}. Each topic is planned as 3 minutes.</p>
          {mode === "time" && topicLimit * ORAL_TOPIC_SECONDS < minutes * 60 ? <p className="text-sm text-muted">There are only {countNoun(weak.length, "topic")} to practice, so this sitting ends before the full period.</p> : null}
          <PrimaryButton disabled={topicLimit < 1} onClick={() => void start()}>Practice weak topics</PrimaryButton>
        </section>
      ) : null}
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
