import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { speakText } from "../lib/speech";
import type { ChatMessage, MoodTag, Persona } from "../lib/types";

const MOODS: MoodTag[] = ["neutral", "happy", "sad", "laughing", "calm", "affectionate"];

interface Props {
  persona: Persona;
}

/** After (or anytime): talk to a saved person in their captured style/voice. */
export default function RememberChat({ persona }: Props) {
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [message, setMessage] = useState("");
  const [mood, setMood] = useState<MoodTag>("affectionate");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setHistory([]);
  }, [persona.id]);

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
      speakText(res.reply);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat failed");
    } finally {
      setBusy(false);
    }
  }

  const ready = persona.samples.length > 0 || !!persona.traits.talking_style || !!persona.traits.accent;

  return (
    <div className="chat">
      <h3>Talk with {persona.name}</h3>
      <p className="empty">
        Choose this person — the program answers in {persona.name}&apos;s captured
        accent and talking style. Add many people (Irfan, and others); pick who you
        want to talk with.
      </p>

      {!ready && (
        <p className="status error">
          Few or no voice samples yet. Use Family conversation or Talk with the
          program first so the style is stronger.
        </p>
      )}

      <div className="field">
        <label>Feeling for the reply</label>
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
          <p className="empty">Say hello to {persona.name}…</p>
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
            placeholder={`Talk to ${persona.name}…`}
          />
        </div>
        <div className="row">
          <button className="btn btn-primary" type="submit" disabled={busy || !message.trim()}>
            {busy ? "…" : `Speak with ${persona.name}`}
          </button>
          <button
            className="btn btn-ghost"
            type="button"
            onClick={() => setHistory([])}
          >
            Clear
          </button>
        </div>
      </form>
      {error && <p className="status error">{error}</p>}
      <p className="style-notes">
        Using {persona.samples.length} voice clips
        {persona.traits.accent ? ` · accent: ${persona.traits.accent}` : ""}
        {persona.traits.talking_style ? ` · style: ${persona.traits.talking_style}` : ""}
      </p>
    </div>
  );
}
