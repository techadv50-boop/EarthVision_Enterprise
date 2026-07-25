import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { playAudioUrl, speakText } from "../lib/speech";
import type { ChatMessage, MoodTag, Persona } from "../lib/types";

const MOODS: MoodTag[] = [
  "neutral",
  "happy",
  "sad",
  "laughing",
  "excited",
  "calm",
  "sarcastic",
];

interface Props {
  persona: Persona;
}

export default function ChatPanel({ persona }: Props) {
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [message, setMessage] = useState("");
  const [mood, setMood] = useState<MoodTag>("neutral");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [styleNotes, setStyleNotes] = useState<string[]>([]);
  const [engine, setEngine] = useState(persona.ai_engine);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setHistory([]);
    setStyleNotes([]);
    setEngine(persona.ai_engine);
  }, [persona.id, persona.ai_engine]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const text = message.trim();
    if (!text || busy) return;
    setBusy(true);
    setError("");
    const nextHistory = [...history, { role: "user" as const, content: text }];
    setHistory(nextHistory);
    setMessage("");
    try {
      const res = await api.chat(persona.id, {
        message: text,
        history,
        mood,
        speak: true,
      });
      setHistory([...nextHistory, { role: "assistant", content: res.reply }]);
      setStyleNotes(res.style_notes);
      setEngine(res.engine);
      if (res.audio_url) {
        await playAudioUrl(res.audio_url);
      } else {
        speakText(res.reply);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chat">
      <h3>Talk with the persona</h3>
      <p className="empty">
        Background AI ({engine}) replies in {persona.name}&apos;s fed voice and
        talking style.
      </p>

      <div className="field">
        <label>Reply mood target</label>
        <div className="mood-row">
          {MOODS.map((m) => (
            <button
              key={m}
              type="button"
              className={`mood-chip ${mood === m ? "on" : ""}`}
              onClick={() => setMood(m)}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      <div className="chat-log">
        {history.length === 0 && (
          <p className="empty">Ask anything. Replies follow the captured persona.</p>
        )}
        {history.map((item, idx) => (
          <div key={`${item.role}-${idx}`} className={`bubble ${item.role}`}>
            <span className="who">{item.role === "user" ? "You" : persona.name}</span>
            {item.content}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <form onSubmit={onSubmit}>
        <div className="field">
          <label>Your message</label>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder={`Ask ${persona.name} something…`}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void onSubmit(e);
              }
            }}
          />
        </div>
        <div className="row">
          <button className="btn btn-primary" type="submit" disabled={busy || !message.trim()}>
            {busy ? "Thinking…" : "Send & hear reply"}
          </button>
          <button
            className="btn btn-ghost"
            type="button"
            onClick={() => {
              setHistory([]);
              setStyleNotes([]);
            }}
          >
            Clear chat
          </button>
        </div>
      </form>

      {error && <p className="status error">{error}</p>}
      {styleNotes.length > 0 && (
        <div className="style-notes">
          Style guide used: {styleNotes.join(" · ")}
        </div>
      )}
    </div>
  );
}
