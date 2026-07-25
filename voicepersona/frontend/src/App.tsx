import { FormEvent, useEffect, useState } from "react";
import ChatPanel from "./components/ChatPanel";
import PersonaEditor from "./components/PersonaEditor";
import SampleRecorder from "./components/SampleRecorder";
import { api, sampleAudioUrl } from "./lib/api";
import type { EngineInfo, Persona } from "./lib/types";

export default function App() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [engines, setEngines] = useState<EngineInfo[]>([]);
  const [newName, setNewName] = useState("");
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
      const nextId =
        preferId ||
        selectedId ||
        (list[0] ? list[0].id : null);
      setSelectedId(nextId && list.some((p) => p.id === nextId) ? nextId : list[0]?.id || null);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not reach VoxPersona API. Start the backend on port 8790.",
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
        description: "New voice persona",
        ai_engine: "eliza",
      });
      setNewName("");
      await refresh(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  async function removePersona(id: string) {
    if (!confirm("Delete this persona and all voice samples?")) return;
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
            Feed a person&apos;s voice, accent, laugh, sadness, and talking style —
            then let a background AI reply in that same voice.
          </p>
        </div>
      </header>

      {error && <p className="status error">{error}</p>}

      <div className="layout">
        <aside className="panel">
          <h2>Voices</h2>
          <form onSubmit={createPersona} style={{ marginBottom: "0.9rem" }}>
            <div className="field">
              <label>New persona</label>
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Person name"
              />
            </div>
            <button className="btn btn-primary" type="submit" disabled={busy || !newName.trim()}>
              Add voice
            </button>
          </form>

          <div className="persona-list">
            {loading && <p className="empty">Loading…</p>}
            {!loading && personas.length === 0 && (
              <p className="empty">No voices yet. Add a person to begin.</p>
            )}
            {personas.map((persona) => (
              <button
                key={persona.id}
                type="button"
                className={`persona-item ${persona.id === selectedId ? "active" : ""}`}
                onClick={() => setSelectedId(persona.id)}
              >
                <strong>{persona.name}</strong>
                <small>
                  {persona.samples.length} samples · AI: {persona.ai_engine}
                </small>
              </button>
            ))}
          </div>
        </aside>

        <main className="stack">
          {!selected && !loading && (
            <section className="panel">
              <h2>Start with a voice</h2>
              <p className="empty">
                Create a persona, record how they talk, then chat. Eliza runs in the
                background by default; switch to an OpenAI-compatible LLM anytime.
              </p>
            </section>
          )}

          {selected && (
            <>
              <section className="panel grid-2">
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
                <div>
                  <SampleRecorder
                    busy={busy}
                    onSave={async (payload) => {
                      setBusy(true);
                      try {
                        await api.uploadSample(
                          selected.id,
                          payload.blob,
                          {
                            kind: payload.kind,
                            transcript: payload.transcript,
                            accent: payload.accent,
                            talking_style: payload.talking_style,
                            moods: payload.moods,
                            notes: payload.notes,
                            duration_ms: payload.duration_ms,
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

                  <div style={{ marginTop: "1.2rem" }}>
                    <h3>Captured samples</h3>
                    <div className="sample-list">
                      {selected.samples.length === 0 && (
                        <p className="empty">No samples yet.</p>
                      )}
                      {selected.samples.map((sample) => (
                        <div key={sample.id} className="sample-item">
                          <strong>
                            {sample.kind}
                            {sample.moods.length ? ` · ${sample.moods.join(", ")}` : ""}
                          </strong>
                          <p className="sample-meta">
                            {[sample.accent, sample.talking_style, sample.transcript]
                              .filter(Boolean)
                              .join(" · ") || "No transcript notes"}
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
                                const updated = await api.deleteSample(
                                  selected.id,
                                  sample.id,
                                );
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
                        Delete persona
                      </button>
                    </div>
                  </div>
                </div>
              </section>

              <section className="panel">
                <ChatPanel persona={selected} />
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
