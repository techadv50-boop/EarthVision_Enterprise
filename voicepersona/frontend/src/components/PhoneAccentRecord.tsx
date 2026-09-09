import { useEffect, useRef, useState } from "react";
import type { Persona } from "../lib/types";

interface Props {
  persona: Persona;
  busy?: boolean;
  onSaved: (payload: {
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
 * Phone accent recording — hold the phone near the person and record.
 * Auto-detects language, accent, and talking style.
 */
export default function PhoneAccentRecord({ persona, busy, onSaved }: Props) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [savedCount, setSavedCount] = useState(0);
  const [liveLine, setLiveLine] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState(
    "Hold the phone near them and tap Record accent. Speak naturally in their language.",
  );

  const mediaRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const startedAt = useRef(0);
  const timerRef = useRef<number | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const keepRecognizing = useRef(false);
  const transcriptBuffer = useRef("");

  useEffect(() => {
    return () => {
      void stopAll(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startSpeech() {
    const Ctor = getSpeechRecognition();
    if (!Ctor) {
      setStatus(
        "Recording accent on phone mic… (Update Android System WebView for live transcript.)",
      );
      return;
    }
    const recognition = new Ctor();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";
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
    recognition.onerror = () => {};
    recognition.onend = () => {
      if (keepRecognizing.current) {
        try {
          recognition.start();
        } catch {
          /* ignore */
        }
      }
    };
    recognitionRef.current = recognition;
    keepRecognizing.current = true;
    try {
      recognition.start();
    } catch {
      /* ignore */
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
      setLiveLine("");
      recorder.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data);
      };
      mediaRef.current = recorder;
      startedAt.current = Date.now();
      setSeconds(0);
      timerRef.current = window.setInterval(() => setSeconds((s) => s + 1), 1000);
      recorder.start(1000);
      startSpeech();
      setRecording(true);
      setStatus(
        `Recording ${persona.name}'s accent on this phone. Ask them to talk, read, or tell a short story.`,
      );
    } catch {
      setError(
        "Phone microphone permission is required. Allow mic access for VoxPersona.",
      );
    }
  }

  async function stopAll(save = true) {
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
    stopSpeech();

    const recorder = mediaRef.current;
    const finish = async () => {
      if (!save) return;
      const parts = chunksRef.current;
      chunksRef.current = [];
      if (!parts.length || !recorder) return;
      const blob = new Blob(parts, { type: recorder.mimeType || "audio/webm" });
      if (blob.size < 800) {
        setStatus("Recording was too short. Try again for a few seconds.");
        return;
      }
      const ext = blob.type.includes("ogg") ? "ogg" : "webm";
      const transcript = transcriptBuffer.current.trim();
      transcriptBuffer.current = "";
      setLiveLine("");
      setStatus("Saving and detecting accent automatically…");
      await onSaved({
        blob,
        filename: `phone_accent_${Date.now()}.${ext}`,
        transcript,
        duration_ms: Date.now() - startedAt.current,
      });
      setSavedCount((n) => n + 1);
      setStatus(
        "Accent sample saved. Record again anytime for a stronger accent match.",
      );
    };

    if (recorder && recorder.state !== "inactive") {
      await new Promise<void>((resolve) => {
        recorder.onstop = () => {
          void finish().finally(resolve);
        };
        recorder.stop();
      });
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    mediaRef.current = null;
    setRecording(false);
  }

  const accent = persona.traits.accent;
  const language = persona.traits.language;

  return (
    <div className="family-only">
      <h3>Phone accent recording</h3>
      <p className="empty">
        Use this phone&apos;s microphone to capture {persona.name}&apos;s accent.
        Hold the phone near them, tap the button, and let them speak. Language and
        accent are detected automatically.
      </p>

      {recording && (
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
        {!recording ? (
          <button
            className="btn btn-accent btn-listen"
            type="button"
            onClick={start}
            disabled={busy}
          >
            Record accent on phone
          </button>
        ) : (
          <button
            className="btn btn-danger btn-listen"
            type="button"
            onClick={() => void stopAll(true)}
          >
            <span className="rec-dot" />
            Stop & save accent ({seconds}s)
          </button>
        )}
        <span className="status">Accent clips saved: {savedCount}</span>
      </div>

      <p className="status">{status}</p>
      {error && <p className="status error">{error}</p>}

      {(language || accent) && (
        <div className="auto-traits">
          <h4>Detected so far</h4>
          <div className="mood-row">
            {language && <span className="mood-chip on">Language: {language}</span>}
            {accent && <span className="mood-chip on">Accent: {accent}</span>}
            {persona.traits.talking_style && (
              <span className="mood-chip on">Style: {persona.traits.talking_style}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
