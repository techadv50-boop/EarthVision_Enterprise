import { FormEvent, useEffect, useState } from "react";
import type { EngineInfo, Persona, PersonaTraits } from "../lib/types";

interface Props {
  persona: Persona;
  engines: EngineInfo[];
  onSave: (patch: {
    name: string;
    description: string;
    ai_engine: string;
    traits: PersonaTraits;
    voice_clone_id: string | null;
  }) => Promise<void>;
}

function listToText(items: string[]) {
  return items.join(", ");
}

function textToList(value: string) {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function PersonaEditor({ persona, engines, onSave }: Props) {
  const [name, setName] = useState(persona.name);
  const [description, setDescription] = useState(persona.description);
  const [aiEngine, setAiEngine] = useState(persona.ai_engine || "eliza");
  const [voiceCloneId, setVoiceCloneId] = useState(persona.voice_clone_id || "");
  const [traits, setTraits] = useState(persona.traits);
  const [fillers, setFillers] = useState(listToText(persona.traits.filler_words));
  const [catchphrases, setCatchphrases] = useState(
    listToText(persona.traits.catchphrases),
  );
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    setName(persona.name);
    setDescription(persona.description);
    setAiEngine(persona.ai_engine || "eliza");
    setVoiceCloneId(persona.voice_clone_id || "");
    setTraits(persona.traits);
    setFillers(listToText(persona.traits.filler_words));
    setCatchphrases(listToText(persona.traits.catchphrases));
  }, [persona]);

  function patchTrait<K extends keyof PersonaTraits>(key: K, value: PersonaTraits[K]) {
    setTraits((prev) => ({ ...prev, [key]: value }));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setStatus("");
    try {
      await onSave({
        name,
        description,
        ai_engine: aiEngine,
        voice_clone_id: voiceCloneId.trim() || null,
        traits: {
          ...traits,
          filler_words: textToList(fillers),
          catchphrases: textToList(catchphrases),
        },
      });
      setStatus("Persona profile saved.");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <h3>Persona profile</h3>
      <div className="field">
        <label>Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </div>
      <div className="field">
        <label>Description</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Who is this person? How should the agent sound overall?"
        />
      </div>
      <div className="row">
        <div className="field" style={{ flex: 1, minWidth: 160 }}>
          <label>Accent</label>
          <input
            value={traits.accent}
            onChange={(e) => patchTrait("accent", e.target.value)}
          />
        </div>
        <div className="field" style={{ flex: 1, minWidth: 160 }}>
          <label>Talking style</label>
          <input
            value={traits.talking_style}
            onChange={(e) => patchTrait("talking_style", e.target.value)}
          />
        </div>
      </div>
      <div className="row">
        <div className="field" style={{ flex: 1, minWidth: 160 }}>
          <label>Laugh style</label>
          <input
            value={traits.laugh_style}
            onChange={(e) => patchTrait("laugh_style", e.target.value)}
            placeholder="short haha, deep chuckle…"
          />
        </div>
        <div className="field" style={{ flex: 1, minWidth: 160 }}>
          <label>Sadness style</label>
          <input
            value={traits.sadness_style}
            onChange={(e) => patchTrait("sadness_style", e.target.value)}
            placeholder="soft, trailing off…"
          />
        </div>
      </div>
      <div className="field">
        <label>Vocabulary / phrasing notes</label>
        <textarea
          value={traits.vocabulary_notes}
          onChange={(e) => patchTrait("vocabulary_notes", e.target.value)}
        />
      </div>
      <div className="field">
        <label>Filler words (comma separated)</label>
        <input value={fillers} onChange={(e) => setFillers(e.target.value)} />
      </div>
      <div className="field">
        <label>Catchphrases (comma separated)</label>
        <input value={catchphrases} onChange={(e) => setCatchphrases(e.target.value)} />
      </div>
      <div className="field">
        <label>Background AI engine</label>
        <select value={aiEngine} onChange={(e) => setAiEngine(e.target.value)}>
          {engines.map((engine) => (
            <option key={engine.id} value={engine.id}>
              {engine.name}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label>Optional voice clone ID (ElevenLabs / OpenAI voice)</label>
        <input
          value={voiceCloneId}
          onChange={(e) => setVoiceCloneId(e.target.value)}
          placeholder="Leave blank to use browser speech"
        />
      </div>
      <div className="row">
        <button className="btn btn-primary" type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save persona"}
        </button>
        {status && <span className="status">{status}</span>}
      </div>
    </form>
  );
}
