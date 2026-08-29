import { useEffect, useRef, useState } from "react";
import type { Persona } from "../lib/types";

interface Props {
  persona: Persona;
  busy?: boolean;
  onChunk: (payload: {
    blob: Blob;
    filename: string;
    transcript: string;
    duration_ms: number;
  }) => Promise<void>;
}

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>;
};

function getSpeechRecognition(): (new () => SpeechRecognitionLike) | null {
  const w = window as Window & {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

/**
 * Family conversation: only Start/Stop listening.
 * Language, accent, talking style, laugh/sadness are captured automatically.
 */
export default function FamilyCapture({ persona, busy, onChunk }: Props) {
  const [listening, setListening] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [chunksSaved, setChunksSaved] = useState(0);
  const [liveLine, setLiveLine] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState(
    "Put the mic/headphones on them, then start listening. Accent and style are captured automatically.",
  );

  const mediaRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const startedAt = useRef(0);
  const timerRef = useRef<number | null>(null);
  const rotateRef = useRef<number | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const keepRecognizing = useRef(false);
  const transcriptBuffer = useRef("");

  useEffect(() => {
    return () => stopAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startSpeech() {
    const Ctor = getSpeechRecognition();
    if (!Ctor) {
      setStatus(
        "Listening for voice… (This browser has no speech recognition; audio is still saved. Use Chrome for auto language/accent.)",
      );
      return;
    }
    const recognition = new Ctor();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US"; // engine still hears mixed Punjabi/Urdu/English words for heuristics/LLM
    recognition.onresult = (event) => {
      let interim = "";
      let finalChunk = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const text = event.results[i][0].transcript;
        if (event.results[i].isFinal) finalChunk += `${text} `;
        else interim += text;
      }
      if (finalChunk.trim()) {
        transcriptBuffer.current = `${transcriptBuffer.current} ${finalChunk}`.trim();
      }
      setLiveLine((interim || finalChunk || transcriptBuffer.current).trim());
    };
    recognition.onerror = () => {
      /* keep audio recording even if speech API glitches */
    };
    recognition.onend = () => {
      if (keepRecognizing.current) {
        try {
          recognition.start();
        } catch {
          /* ignore restart races */
        }
      }
    };
    recognitionRef.current = recognition;
    keepRecognizing.current = true;
    try {
      recognition.start();
    } catch {
      /* already started */
    }
  }

  function stopSpeech() {
    keepRecognizing.current = false;
    try {
      recognitionRef.current?.stop();
    } catch {
      /* ignore */
    }
    recognitionRef.current = null;
  }

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
    const transcript = transcriptBuffer.current.trim();
    transcriptBuffer.current = "";
    setLiveLine("");

    setStatus(final ? "Saving and auto-analyzing voice…" : "Auto-capturing language, accent & style…");
    await onChunk({
      blob,
      filename: `family_${Date.now()}.${ext}`,
      transcript,
      duration_ms,
    });
    setChunksSaved((n) => n + 1);
    setStatus(
      final
        ? "Listening stopped. Voice and style were captured automatically."
        : `Still listening to ${persona.name}…`,
    );
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
      transcriptBuffer.current = "";
      recorder.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data);
      };
      mediaRef.current = recorder;
      startedAt.current = Date.now();
      setSeconds(0);
      setChunksSaved(0);
      timerRef.current = window.setInterval(() => setSeconds((s) => s + 1), 1000);
      rotateRef.current = window.setInterval(() => {
        void flushChunk(false);
      }, 20000);
      recorder.start(1000);
      startSpeech();
      setListening(true);
      setStatus(
        `Listening to ${persona.name}. Family can talk naturally — language, accent, and style are detected automatically.`,
      );
    } catch {
      setError(
        "Could not access the microphone/headphones. Attach the recorder to the person and allow mic permission.",
      );
    }
  }

  function stopAll() {
    if (timerRef.current) window.clearInterval(timerRef.current);
    if (rotateRef.current) window.clearInterval(rotateRef.current);
    timerRef.current = null;
    rotateRef.current = null;
    stopSpeech();
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

  const traits = persona.traits;

  return (
    <div className="family-only">
      <h3>Family conversation</h3>
      <p className="empty">
        Seat {persona.name} with family. Put the headphone mic on {persona.name}.
        Press start — the program records and automatically captures language, accent,
        talking style, laugh, and mood. No typing needed.
      </p>

      {listening && (
        <div className="wave" aria-hidden>
          {Array.from({ length: 8 }).map((_, i) => (
            <span key={i} />
          ))}
        </div>
      )}

      {liveLine && (
        <p className="live-line">
          Hearing: <em>{liveLine}</em>
        </p>
      )}

      <div className="row family-actions">
        {!listening ? (
          <button className="btn btn-accent btn-listen" type="button" onClick={start} disabled={busy}>
            Start listening to {persona.name}
          </button>
        ) : (
          <button className="btn btn-danger btn-listen" type="button" onClick={stopAll}>
            <span className="rec-dot" />
            Stop listening ({seconds}s)
          </button>
        )}
        <span className="status">Saved clips this session: {chunksSaved}</span>
      </div>

      <p className="status">{status}</p>
      {error && <p className="status error">{error}</p>}

      {(traits.language || traits.accent || traits.talking_style || traits.laugh_style) && (
        <div className="auto-traits">
          <h4>Auto-captured so far</h4>
          <div className="mood-row">
            {traits.language && <span className="mood-chip on">Language: {traits.language}</span>}
            {traits.accent && <span className="mood-chip on">Accent: {traits.accent}</span>}
            {traits.talking_style && (
              <span className="mood-chip on">Style: {traits.talking_style}</span>
            )}
            {traits.laugh_style && (
              <span className="mood-chip on">Laugh: {traits.laugh_style}</span>
            )}
            {traits.sadness_style && (
              <span className="mood-chip on">Sadness: {traits.sadness_style}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
