import { FormEvent, useState } from "react";
import { api } from "../lib/api";
import type { AuthUser, PublicConfig } from "../lib/auth";

interface Props {
  config: PublicConfig | null;
  onLoggedIn: (user: AuthUser, warning?: string) => void;
}

export default function AuthScreen({ config, onLoggedIn }: Props) {
  const [tab, setTab] = useState<"login" | "register">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const price = config
    ? `${config.subscription_currency} ${config.subscription_price}/month`
    : "monthly plan";

  async function onLogin(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const data = await api.login({ email, password });
      onLoggedIn(data.user, data.warning);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  async function onRegister(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const data = await api.register({ name, email, password });
      setMessage(data.message);
      setTab("login");
      setPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-panel panel">
        <h1 className="brand-mark">
          Vox<span>Persona</span>
        </h1>
        <p className="brand-sub" style={{ marginBottom: "1.2rem" }}>
          Create an account to keep a loved one&apos;s voice. After admin approval,
          your monthly subscription unlocks the studio.
        </p>

        <div className="mode-tabs" style={{ marginBottom: "1rem" }}>
          <button type="button" className={tab === "login" ? "on" : ""} onClick={() => setTab("login")}>
            Log in
          </button>
          <button
            type="button"
            className={tab === "register" ? "on" : ""}
            onClick={() => setTab("register")}
          >
            Create account
          </button>
        </div>

        {tab === "login" ? (
          <form onSubmit={onLogin}>
            <div className="field">
              <label>Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>
            <div className="field">
              <label>Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </div>
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {busy ? "Please wait…" : "Enter"}
            </button>
          </form>
        ) : (
          <form onSubmit={onRegister}>
            <div className="field">
              <label>Your name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="field">
              <label>Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="field">
              <label>Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
              />
            </div>
            <p className="status" style={{ marginBottom: "0.8rem" }}>
              Plan: <strong>{price}</strong> · Account requests go to the admin for
              Allow / Decline / Restrict.
            </p>
            <button className="btn btn-accent" type="submit" disabled={busy}>
              {busy ? "Submitting…" : "Request account"}
            </button>
          </form>
        )}

        {message && <p className="status" style={{ color: "var(--ok)", marginTop: "0.9rem" }}>{message}</p>}
        {error && <p className="status error" style={{ marginTop: "0.9rem" }}>{error}</p>}
      </div>
    </div>
  );
}
