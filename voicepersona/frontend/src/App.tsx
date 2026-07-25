import { FormEvent, useEffect, useState } from "react";
import FamilyCapture from "./components/FamilyCapture";
import PersonaEditor from "./components/PersonaEditor";
import ProgramTalk from "./components/ProgramTalk";
import RememberChat from "./components/RememberChat";
import { api, sampleAudioUrl } from "./lib/api";
import type { AppMode, EngineInfo, Persona } from "./lib/types";

export default function App() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [engines, setEngines] = useState<EngineInfo[]>([]);
  const [newName, setNewName] = useState("");
  const [mode, setMode] = useState<AppMode>("family");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const selected = personas.find((p) => p.id === selectedId) || null;

  async function refresh(preferId?: string | null) {
    setLoading(true);
    setError("");
    try {
      const [list, engineRes] = await Promise.all([api.listPersonas(), api.engines()]);
      setPersonas(list);
      setEngines(engineRes.engines);
      const nextId = preferId || selectedId || list[0]?.id || null;
      setSelectedId(nextId && list.some((p) => p.id === nextId) ? nextId : list[0]?.id || null);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "API not reachable. On cPanel, upload the deploy folder. Locally, start the PHP API.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function createPersona(e: FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setBusy(true);
    try {
      const created = await api.createPersona({
        name: newName.trim(),
        description: "Loved one’s voice memory",
        ai_engine: "eliza",
      });
      setNewName("");
      await refresh(created.id);
      setMode("family");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  async function removePersona(id: string) {
    if (!confirm("Delete this person and all saved voice clips?")) return;
    setBusy(true);
    try {
      await api.deletePersona(id);
      await refresh(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="brand-bar">
        <div>
          <h1 className="brand-mark">
            Vox<span>Persona</span>
          </h1>
          <p className="brand-sub">
            Capture a loved one’s voice while they are still here — through family
            conversation or gentle talks with the program — then speak with that same
            accent and style whenever you need to.
          </p>
        </div>
      </header>

      {error && <p className="status error">{error}</p>}

      <div className="layout">
        <aside className="panel">
          <h2>People</h2>
          <p className="empty" style={{ marginTop: 0 }}>
            Add many voices — Irfan, Amma, Abu — then choose who to talk with.
          </p>
          <form onSubmit={createPersona} style={{ marginBottom: "0.9rem" }}>
            <div className="field">
              <label>Add a person</label>
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="e.g. Irfan"
              />
            </div>
            <button className="btn btn-primary" type="submit" disabled={busy || !newName.trim()}>
              Save person
            </button>
          </form>

          <div className="persona-list">
            {loading && <p className="empty">Loading…</p>}
            {!loading && personas.length === 0 && (
              <p className="empty">No people yet. Add the first loved one.</p>
            )}
            {personas.map((persona) => (
              <button
                key={persona.id}
                type="button"
                className={`persona-item ${persona.id === selectedId ? "active" : ""}`}
                onClick={() => setSelectedId(persona.id)}
              >
                <strong>{persona.name}</strong>
                <small>{persona.samples.length} voice clips saved</small>
              </button>
            ))}
          </div>
        </aside>

        <main className="stack">
          {!selected && !loading && (
            <section className="panel">
              <h2>How it works</h2>
              <ol className="howto">
                <li>Add a person (example: Irfan).</li>
                <li>
                  <strong>Family talk:</strong> son/daughter sits with them; mic on the
                  elder; program records their voice.
                </li>
                <li>
                  <strong>Talk with program:</strong> elder chats on any topic; program
                  replies and keeps recording.
                </li>
                <li>
                  Later, open that person and <strong>Talk with them</strong> in the same
                  accent and style.
                </li>
              </ol>
            </section>
          )}

          {selected && (
            <>
              <section className="panel">
                <div className="mode-tabs" role="tablist" aria-label="Modes">
                  <button
                    type="button"
                    className={mode === "family" ? "on" : ""}
                    onClick={() => setMode("family")}
                  >
                    1. Family conversation
                  </button>
                  <button
                    type="button"
                    className={mode === "program" ? "on" : ""}
                    onClick={() => setMode("program")}
                  >
                    2. Talk with program
                  </button>
                  <button
                    type="button"
                    className={mode === "remember" ? "on" : ""}
                    onClick={() => setMode("remember")}
                  >
                    3. Talk with {selected.name}
                  </button>
                </div>
              </section>

              {mode === "family" && (
                <section className="panel grid-2">
                  <FamilyCapture
                    persona={selected}
                    busy={busy}
                    onChunk={async (payload) => {
                      setBusy(true);
                      try {
                        await api.uploadSample(
                          selected.id,
                          payload.blob,
                          {
                            kind: "speech",
                            transcript: payload.transcript,
                            accent: payload.accent,
                            talking_style: payload.talking_style,
                            moods: ["neutral"],
                            notes: payload.notes,
                            duration_ms: payload.duration_ms,
                            source: "family_talk",
                          },
                          payload.filename,
                        );
                        const fresh = await api.getPersona(selected.id);
                        setPersonas((prev) =>
                          prev.map((p) => (p.id === fresh.id ? fresh : p)),
                        );
                      } finally {
                        setBusy(false);
                      }
                    }}
                  />
                  <PersonaEditor
                    persona={selected}
                    engines={engines}
                    onSave={async (patch) => {
                      const updated = await api.updatePersona(selected.id, patch);
                      setPersonas((prev) =>
                        prev.map((p) => (p.id === updated.id ? updated : p)),
                      );
                    }}
                  />
                </section>
              )}

              {mode === "program" && (
                <section className="panel">
                  <ProgramTalk
                    persona={selected}
                    onVoiceSaved={async () => {
                      const fresh = await api.getPersona(selected.id);
                      setPersonas((prev) =>
                        prev.map((p) => (p.id === fresh.id ? fresh : p)),
                      );
                    }}
                  />
                </section>
              )}

              {mode === "remember" && (
                <section className="panel">
                  <RememberChat persona={selected} />
                </section>
              )}

              <section className="panel">
                <h3>Saved voice clips for {selected.name}</h3>
                <div className="sample-list">
                  {selected.samples.length === 0 && (
                    <p className="empty">No clips yet — start a family conversation or program talk.</p>
                  )}
                  {[...selected.samples].reverse().map((sample) => (
                    <div key={sample.id} className="sample-item">
                      <strong>
                        {sample.source || sample.kind}
                        {sample.moods?.length ? ` · ${sample.moods.join(", ")}` : ""}
                      </strong>
                      <p className="sample-meta">
                        {[sample.accent, sample.talking_style, sample.transcript]
                          .filter(Boolean)
                          .join(" · ") || "Voice clip"}
                      </p>
                      <audio
                        controls
                        src={sampleAudioUrl(selected.id, sample.filename)}
                        style={{ width: "100%" }}
                      />
                      <div className="row" style={{ marginTop: "0.45rem" }}>
                        <button
                          type="button"
                          className="btn btn-danger"
                          onClick={async () => {
                            const updated = await api.deleteSample(selected.id, sample.id);
                            setPersonas((prev) =>
                              prev.map((p) => (p.id === updated.id ? updated : p)),
                            );
                          }}
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="row" style={{ marginTop: "0.9rem" }}>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => removePersona(selected.id)}
                  >
                    Delete person
                  </button>
                </div>
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
