import { useEffect, useRef, useState } from "react";
import type { MoodTag, SampleKind } from "../lib/types";

const KINDS: SampleKind[] = [
  "speech",
  "laughing",
  "sadness",
  "accent",
  "style",
  "other",
];

const MOODS: MoodTag[] = [
  "neutral",
  "happy",
  "sad",
  "laughing",
  "angry",
  "excited",
  "calm",
  "anxious",
  "affectionate",
  "sarcastic",
];

interface Props {
  busy?: boolean;
  onSave: (payload: {
    blob: Blob;
    filename: string;
    kind: SampleKind;
    transcript: string;
    accent: string;
    talking_style: string;
    moods: MoodTag[];
    notes: string;
    duration_ms: number;
  }) => Promise<void>;
}

export default function SampleRecorder({ busy, onSave }: Props) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [kind, setKind] = useState<SampleKind>("speech");
  const [transcript, setTranscript] = useState("");
  const [accent, setAccent] = useState("");
  const [talkingStyle, setTalkingStyle] = useState("");
  const [notes, setNotes] = useState("");
  const [moods, setMoods] = useState<MoodTag[]>(["neutral"]);
  const [error, setError] = useState("");
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const startedAt = useRef(0);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
      mediaRef.current?.stream.getTracks().forEach((t) => t.stop());
    };
  }, []);

  async function start() {
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });
        const duration_ms = Date.now() - startedAt.current;
        const ext = blob.type.includes("ogg") ? "ogg" : "webm";
        await onSave({
          blob,
          filename: `capture.${ext}`,
          kind,
          transcript,
          accent,
          talking_style: talkingStyle,
          moods,
          notes,
          duration_ms,
        });
        stream.getTracks().forEach((t) => t.stop());
      };
      mediaRef.current = recorder;
      startedAt.current = Date.now();
      setSeconds(0);
      timerRef.current = window.setInterval(() => {
        setSeconds((s) => s + 1);
      }, 1000);
      recorder.start();
      setRecording(true);
    } catch {
      setError("Microphone access is required to record voice samples.");
    }
  }

  function stop() {
    if (timerRef.current) window.clearInterval(timerRef.current);
    mediaRef.current?.stop();
    setRecording(false);
  }

  function toggleMood(mood: MoodTag) {
    setMoods((prev) =>
      prev.includes(mood) ? prev.filter((m) => m !== mood) : [...prev, mood],
    );
  }

  return (
    <div>
      <h3>Capture voice & style</h3>
      <p className="empty">
        Record speech, laughter, sadness, accent, and talking style. Tag what you
        hear so the AI can reply the same way.
      </p>

      <div className="field">
        <label>Sample type</label>
        <select value={kind} onChange={(e) => setKind(e.target.value as SampleKind)}>
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label>Transcript / what they said</label>
        <textarea
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          placeholder="Type what was said in this clip…"
        />
      </div>

      <div className="row">
        <div className="field" style={{ flex: 1, minWidth: 160 }}>
          <label>Accent</label>
          <input
            value={accent}
            onChange={(e) => setAccent(e.target.value)}
            placeholder="e.g. Nigerian, Southern US, London"
          />
        </div>
        <div className="field" style={{ flex: 1, minWidth: 160 }}>
          <label>Talking style</label>
          <input
            value={talkingStyle}
            onChange={(e) => setTalkingStyle(e.target.value)}
            placeholder="fast, soft, witty, formal…"
          />
        </div>
      </div>

      <div className="field">
        <label>Moods in this clip</label>
        <div className="mood-row">
          {MOODS.map((mood) => (
            <button
              key={mood}
              type="button"
              className={`mood-chip ${moods.includes(mood) ? "on" : ""}`}
              onClick={() => toggleMood(mood)}
            >
              {mood}
            </button>
          ))}
        </div>
      </div>

      <div className="field">
        <label>Notes (laugh style, sadness tone, everything else)</label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="e.g. short breathy laugh · voice drops when sad · says 'you know' a lot"
        />
      </div>

      {recording && (
        <div className="wave" aria-hidden>
          {Array.from({ length: 8 }).map((_, i) => (
            <span key={i} />
          ))}
        </div>
      )}

      <div className="row">
        {!recording ? (
          <button className="btn btn-accent" type="button" onClick={start} disabled={busy}>
            Start recording
          </button>
        ) : (
          <button className="btn btn-danger" type="button" onClick={stop}>
            <span className="rec-dot" />
            Stop ({seconds}s)
          </button>
        )}
        <span className="status">
          Tip: capture several moods and styles for stronger replies.
        </span>
      </div>
      {error && <p className="status error">{error}</p>}
    </div>
  );
}
