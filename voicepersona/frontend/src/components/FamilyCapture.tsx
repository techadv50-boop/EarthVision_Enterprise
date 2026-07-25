import { useEffect, useRef, useState } from "react";
import type { Persona } from "../lib/types";

interface Props {
  persona: Persona;
  busy?: boolean;
  onChunk: (payload: {
    blob: Blob;
    filename: string;
    transcript: string;
    accent: string;
    talking_style: string;
    notes: string;
    duration_ms: number;
  }) => Promise<void>;
}

/**
 * Mode 1: Elder + family sit together.
 * Headphones/mic on the elder — we continuously capture their side of the talk.
 */
export default function FamilyCapture({ persona, busy, onChunk }: Props) {
  const [listening, setListening] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [chunksSaved, setChunksSaved] = useState(0);
  const [transcript, setTranscript] = useState("");
  const [accent, setAccent] = useState(persona.traits.accent || "");
  const [talkingStyle, setTalkingStyle] = useState(persona.traits.talking_style || "");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("Ready when the family conversation begins.");

  const mediaRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const startedAt = useRef(0);
  const timerRef = useRef<number | null>(null);
  const rotateRef = useRef<number | null>(null);
  const metaRef = useRef({ transcript, accent, talkingStyle, notes });

  useEffect(() => {
    metaRef.current = { transcript, accent, talkingStyle, notes };
  }, [transcript, accent, talkingStyle, notes]);

  useEffect(() => {
    setAccent(persona.traits.accent || "");
    setTalkingStyle(persona.traits.talking_style || "");
  }, [persona.id, persona.traits.accent, persona.traits.talking_style]);

  useEffect(() => {
    return () => stopAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function flushChunk(final = false) {
    const recorder = mediaRef.current;
    if (!recorder || recorder.state === "inactive") return;

    const parts = chunksRef.current;
    chunksRef.current = [];
    if (!parts.length) return;

    const blob = new Blob(parts, { type: recorder.mimeType || "audio/webm" });
    if (blob.size < 1200) return;

    const duration_ms = Date.now() - startedAt.current;
    startedAt.current = Date.now();
    const ext = blob.type.includes("ogg") ? "ogg" : "webm";
    const meta = metaRef.current;

    setStatus(final ? "Saving final voice clip…" : "Saving voice clip…");
    await onChunk({
      blob,
      filename: `family_${Date.now()}.${ext}`,
      transcript: meta.transcript,
      accent: meta.accent,
      talking_style: meta.talkingStyle,
      notes: meta.notes || "Family conversation capture from elder microphone",
      duration_ms,
    });
    setChunksSaved((n) => n + 1);
    setTranscript("");
    setStatus(final ? "Listening stopped. Voice saved." : "Still listening to the elder…");
  }

  async function start() {
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data);
      };
      mediaRef.current = recorder;
      startedAt.current = Date.now();
      setSeconds(0);
      setChunksSaved(0);
      timerRef.current = window.setInterval(() => setSeconds((s) => s + 1), 1000);
      // Rotate clips every 25s so long family talks are stored as many samples.
      rotateRef.current = window.setInterval(() => {
        void flushChunk(false);
      }, 25000);
      recorder.start(1000);
      setListening(true);
      setStatus(
        `Listening to ${persona.name}. Son/daughter can talk naturally — only this microphone is recorded.`,
      );
    } catch {
      setError(
        "Could not access the microphone/headphones. Attach the recorder to the elder and allow mic permission.",
      );
    }
  }

  function stopAll() {
    if (timerRef.current) window.clearInterval(timerRef.current);
    if (rotateRef.current) window.clearInterval(rotateRef.current);
    timerRef.current = null;
    rotateRef.current = null;
    const recorder = mediaRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.onstop = () => {
        void flushChunk(true);
      };
      recorder.stop();
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    mediaRef.current = null;
    setListening(false);
  }

  return (
    <div>
      <h3>Family conversation capture</h3>
      <p className="empty">
        Seat {persona.name} and their son/daughter together. Put the headphone mic on{" "}
        {persona.name}. When they talk, this program records their voice and accent —
        no login needed for them.
      </p>

      <div className="field">
        <label>Accent you hear</label>
        <input
          value={accent}
          onChange={(e) => setAccent(e.target.value)}
          placeholder="e.g. Punjabi English, soft Karachi, rural accent"
        />
      </div>
      <div className="field">
        <label>Talking style you hear</label>
        <input
          value={talkingStyle}
          onChange={(e) => setTalkingStyle(e.target.value)}
          placeholder="slow, warm, storytelling, short sentences…"
        />
      </div>
      <div className="field">
        <label>Optional: type a line they just said</label>
        <textarea
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          placeholder="Family helper can type memorable phrases here while listening…"
        />
      </div>
      <div className="field">
        <label>Notes (laugh, sadness, habits)</label>
        <input
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="laughs with shoulders, voice softens when sad…"
        />
      </div>

      {listening && (
        <div className="wave" aria-hidden>
          {Array.from({ length: 8 }).map((_, i) => (
            <span key={i} />
          ))}
        </div>
      )}

      <div className="row">
        {!listening ? (
          <button className="btn btn-accent" type="button" onClick={start} disabled={busy}>
            Start listening to {persona.name}
          </button>
        ) : (
          <button className="btn btn-danger" type="button" onClick={stopAll}>
            <span className="rec-dot" />
            Stop listening ({seconds}s)
          </button>
        )}
        <span className="status">
          Saved clips this session: {chunksSaved}
        </span>
      </div>
      <p className="status">{status}</p>
      {error && <p className="status error">{error}</p>}
    </div>
  );
}
