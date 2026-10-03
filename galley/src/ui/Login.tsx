import { useState } from "react";
import { login, register, setToken, type Account } from "../api";

export function Login({ onSignedIn }: { onSignedIn: (user: Account) => void }) {
  const [mode, setMode] = useState<"in" | "up">("in");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <form
      className="panel login-card"
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        setError("");
        setMessage("");
        try {
          if (mode === "up") {
            await register(name, email, password);
            setMode("in");
            setMessage("Account requested. An admin must approve it before you can open the desk.");
            setPassword("");
            return;
          }
          const session = await login(email, password);
          setToken(session.token);
          onSignedIn(session.user);
        } catch (caught) {
          setError(caught instanceof Error ? caught.message : "Could not sign in.");
        } finally {
          setBusy(false);
        }
      }}
    >
      <h1>Galley</h1>
      <p className="muted">galley.drxdhr.com</p>
      <div className="tool-row">
        <button type="button" className={mode === "in" ? "" : "ghost"} onClick={() => setMode("in")}>
          Sign in
        </button>
        <button type="button" className={mode === "up" ? "" : "ghost"} onClick={() => setMode("up")}>
          Request an account
        </button>
      </div>
      {mode === "up" && (
        <label>
          Name
          <input value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" />
        </label>
      )}
      <label>
        Email
        <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" required />
      </label>
      <label>
        Password
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete={mode === "up" ? "new-password" : "current-password"}
          minLength={8}
          required
        />
      </label>
      {error && <p className="error">{error}</p>}
      {message && <p className="muted">{message}</p>}
      <button type="submit" disabled={busy}>
        {mode === "up" ? "Request account" : "Sign in"}
      </button>
    </form>
  );
}
