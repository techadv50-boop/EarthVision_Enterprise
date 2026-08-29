import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { speakText } from "../lib/speech";
import type { ChatMessage, Persona } from "../lib/types";

interface Props {
  persona: Persona;
  onVoiceSaved: () => Promise<void>;
}

/**
 * Mode 2: Elder talks with the program on any topic.
 * Every spoken turn is recorded for voice/accent learning.
 */
export default function ProgramTalk({ persona, onVoiceSaved }: Props) {
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState(
    "Press and hold “Hold to talk”, then release. The program replies and keeps their voice.",
  );

  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const startedAt = useRef(0);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    setHistory([]);
  }, [persona.id]);

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  async function beginRecord() {
    if (recording || busy) return;
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data);
      };
      mediaRef.current = recorder;
      startedAt.current = Date.now();
      recorder.start();
      setRecording(true);
      setStatus(`Listening to ${persona.name}… speak naturally about any topic.`);
    } catch {
      setError("Microphone permission is required for this mode.");
    }
  }

  async function endRecordAndSend(typedFallback?: string) {
    const recorder = mediaRef.current;
    if (!recorder || recorder.state === "inactive") {
      if (typedFallback?.trim()) {
        await sendTurn(typedFallback.trim(), null);
      }
      return;
    }

    const blob: Blob = await new Promise((resolve) => {
      recorder.onstop = () => {
        resolve(
          new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" }),
        );
      };
      recorder.stop();
    });
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    mediaRef.current = null;
    setRecording(false);

    const message =
      typedFallback?.trim() ||
      text.trim() ||
      `(spoken message from ${persona.name})`;
    await sendTurn(message, blob);
    setText("");
  }

  async function sendTurn(message: string, blob: Blob | null) {
    setBusy(true);
    setError("");
    const nextHistory = [...history, { role: "user" as const, content: message }];
    setHistory(nextHistory);
    try {
      if (blob && blob.size > 800) {
        const ext = blob.type.includes("ogg") ? "ogg" : "webm";
        await api.uploadSample(
          persona.id,
          blob,
          {
            kind: "speech",
            transcript: message.startsWith("(spoken") ? "" : message,
            notes: "Captured while talking with the program",
            duration_ms: Date.now() - startedAt.current,
            source: "program_talk",
            auto_analyze: true,
          },
          `program_${Date.now()}.${ext}`,
        );
        await onVoiceSaved();
      }

      const res = await api.chat(persona.id, {
        message,
        history,
        mood: "calm",
        speak: true,
      });
      setHistory([...nextHistory, { role: "assistant", content: res.reply }]);
      speakText(res.reply);
      setStatus("Voice saved. Keep talking to strengthen the memory.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save/talk");
    } finally {
      setBusy(false);
    }
  }

  async function onTypedSubmit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim() || busy) return;
    // If they typed only (no hold-to-talk), still chat — but remind to use mic for voice capture.
    await sendTurn(text.trim(), null);
    setText("");
    setStatus("Reply sent. For voice capture, use Hold to talk.");
  }

  return (
    <div className="chat">
      <h3>Talk with the program</h3>
      <p className="empty">
        {persona.name} can talk about any topic. The program replies gently. The only
        purpose here is to keep recording their real voice and way of speaking.
      </p>

      <div className="chat-log">
        {history.length === 0 && (
          <p className="empty">No talk yet. Hold the button and let them speak.</p>
        )}
        {history.map((item, idx) => (
          <div key={`${item.role}-${idx}`} className={`bubble ${item.role}`}>
            <span className="who">
              {item.role === "user" ? persona.name : "Program"}
            </span>
            {item.content}
          </div>
        ))}
      </div>

      <div className="row" style={{ marginBottom: "0.8rem" }}>
        <button
          type="button"
          className={`btn ${recording ? "btn-danger" : "btn-accent"}`}
          disabled={busy}
          onMouseDown={() => void beginRecord()}
          onMouseUp={() => void endRecordAndSend()}
          onMouseLeave={() => {
            if (recording) void endRecordAndSend();
          }}
          onTouchStart={(e) => {
            e.preventDefault();
            void beginRecord();
          }}
          onTouchEnd={(e) => {
            e.preventDefault();
            void endRecordAndSend();
          }}
        >
          {recording ? (
            <>
              <span className="rec-dot" />
              Release to save & reply
            </>
          ) : (
            "Hold to talk (records voice)"
          )}
        </button>
      </div>

      <form onSubmit={onTypedSubmit}>
        <div className="field">
          <label>Or type what they said (if helper is assisting)</label>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Optional typed message…"
          />
        </div>
        <button className="btn btn-ghost" type="submit" disabled={busy || !text.trim()}>
          Send text only
        </button>
      </form>

      <p className="status">{status}</p>
      {error && <p className="status error">{error}</p>}
    </div>
  );
}
