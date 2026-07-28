import { FormEvent, useEffect, useState } from "react";
import AdminPanel from "./components/AdminPanel";
import AuthScreen from "./components/AuthScreen";
import FamilyCapture from "./components/FamilyCapture";
import ProgramTalk from "./components/ProgramTalk";
import RememberChat from "./components/RememberChat";
import ServerSetup from "./components/ServerSetup";
import { api, sampleAudioUrl } from "./lib/api";
import { getToken, setToken, type AuthUser, type PublicConfig } from "./lib/auth";
import { clearServerUrl, getServerUrl, isNativeApp, needsServerSetup } from "./lib/config";
import type { AppMode, Persona } from "./lib/types";

export default function App() {
  const [bootstrapping, setBootstrapping] = useState(true);
  const [needsServer, setNeedsServer] = useState(needsServerSetup());
  const [user, setUser] = useState<AuthUser | null>(null);
  const [publicConfig, setPublicConfig] = useState<PublicConfig | null>(null);
  const [billingConfig, setBillingConfig] = useState<PublicConfig | null>(null);
  const [authWarning, setAuthWarning] = useState("");
  const [view, setView] = useState<"studio" | "admin">("studio");

  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [mode, setMode] = useState<AppMode>("family");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [renewMsg, setRenewMsg] = useState("");

  const selected = personas.find((p) => p.id === selectedId) || null;
  const subActive = !!user && (user.role === "admin" || user.subscription_active);

  useEffect(() => {
    if (needsServer) {
      setBootstrapping(false);
      return;
    }
    void (async () => {
      try {
        const cfg = await api.publicConfig();
        setPublicConfig(cfg);
      } catch {
        if (isNativeApp()) {
          setNeedsServer(true);
          setBootstrapping(false);
          return;
        }
      }
      if (!getToken()) {
        setBootstrapping(false);
        return;
      }
      try {
        const me = await api.me();
        setUser(me.user);
        setBillingConfig({ ...me.config, app_name: "VoxPersona" });
      } catch {
        setToken(null);
      } finally {
        setBootstrapping(false);
      }
    })();
  }, [needsServer]);

  async function refreshStudio(preferId?: string | null) {
    if (!subActive) return;
    setLoading(true);
    setError("");
    try {
      const list = await api.listPersonas();
      setPersonas(list);
      const nextId = preferId || selectedId || list[0]?.id || null;
      setSelectedId(nextId && list.some((p) => p.id === nextId) ? nextId : list[0]?.id || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load studio");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (user && subActive && view === "studio") {
      void refreshStudio();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, subActive, view]);

  async function createPersona(e: FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setBusy(true);
    try {
      const created = await api.createPersona({
        name: newName.trim(),
        description: "Loved one’s voice memory",
        ai_engine: "discussion",
      });
      setNewName("");
      await refreshStudio(created.id);
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
      await refreshStudio(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  if (bootstrapping) {
    return (
      <div className="auth-shell">
        <p className="status">Loading VoxPersona…</p>
      </div>
    );
  }

  if (needsServer) {
    return (
      <ServerSetup
        initialUrl={getServerUrl()}
        onReady={() => {
          setNeedsServer(false);
          setBootstrapping(true);
        }}
      />
    );
  }

  if (!user) {
    return (
      <AuthScreen
        config={publicConfig}
        onLoggedIn={(u, warning) => {
          setUser(u);
          setAuthWarning(warning || "");
          setView("studio");
        }}
      />
    );
  }

  const priceLabel = billingConfig || publicConfig;
  const priceText = priceLabel
    ? `${priceLabel.subscription_currency} ${priceLabel.subscription_price}/month`
    : "monthly plan";

  return (
    <div className="app-shell">
      <header className="brand-bar">
        <div>
          <h1 className="brand-mark">
            Vox<span>Persona</span>
          </h1>
          <p className="brand-sub">
            Signed in as <strong>{user.name}</strong> ({user.email})
            {user.role === "admin" ? " · Admin" : ""}
            {user.days_remaining !== null && user.role !== "admin"
              ? ` · ${user.days_remaining} days left on subscription`
              : ""}
          </p>
        </div>
        <div className="row">
          {isNativeApp() && (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                clearServerUrl();
                setUser(null);
                setToken(null);
                setNeedsServer(true);
              }}
            >
              Change server
            </button>
          )}
          {user.role === "admin" && (
            <button
              type="button"
              className={`btn ${view === "admin" ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setView(view === "admin" ? "studio" : "admin")}
            >
              {view === "admin" ? "Open studio" : "Admin accounts"}
            </button>
          )}
          <button
            type="button"
            className="btn btn-ghost"
            onClick={async () => {
              await api.logout();
              setUser(null);
              setPersonas([]);
            }}
          >
            Log out
          </button>
        </div>
      </header>

      {(authWarning || !subActive) && (
        <section className="panel sub-banner">
          <h3>Subscription</h3>
          <p className="empty">
            {authWarning ||
              "Your monthly subscription has ended or is inactive. Request renewal to use the studio again."}
            {" "}
            Plan: <strong>{priceText}</strong>
            {user.subscription_ends_at
              ? ` · ended/ends ${new Date(user.subscription_ends_at).toLocaleString()}`
              : ""}
          </p>
          <div className="row">
            <button
              type="button"
              className="btn btn-accent"
              onClick={async () => {
                try {
                  const res = await api.renewRequest();
                  setRenewMsg(res.message);
                } catch (err) {
                  setRenewMsg(err instanceof Error ? err.message : "Request failed");
                }
              }}
            >
              Request renewal email
            </button>
            {renewMsg && <span className="status">{renewMsg}</span>}
          </div>
        </section>
      )}

      {user.role === "admin" && view === "admin" && <AdminPanel />}

      {subActive && view === "studio" && (
        <>
          {error && <p className="status error">{error}</p>}
          {user.role !== "admin" &&
            user.days_remaining !== null &&
            user.days_remaining <= 5 &&
            user.days_remaining >= 0 && (
              <p className="admin-alert">
                Your subscription ends in {user.days_remaining} day(s). Renew soon —
                a reminder email is also sent near expiry.
              </p>
            )}

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
                    <section className="panel">
                      <FamilyCapture
                        persona={selected}
                        busy={busy}
                        onChunk={async (payload) => {
                          setBusy(true);
                          try {
                            const res = await api.uploadSample(
                              selected.id,
                              payload.blob,
                              {
                                kind: "speech",
                                transcript: payload.transcript,
                                duration_ms: payload.duration_ms,
                                source: "family_talk",
                                auto_analyze: true,
                              },
                              payload.filename,
                            );
                            setPersonas((prev) =>
                              prev.map((p) => (p.id === res.persona.id ? res.persona : p)),
                            );
                          } finally {
                            setBusy(false);
                          }
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
                        <p className="empty">
                          No clips yet — start a family conversation or program talk.
                        </p>
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
                        Delete person
                      </button>
                    </div>
                  </section>
                </>
              )}
            </main>
          </div>
        </>
      )}
    </div>
  );
}
