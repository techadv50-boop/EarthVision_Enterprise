import { FormEvent, useState } from "react";
import { apiUrl, normalizeServerUrl, setServerUrl } from "../lib/config";

interface Props {
  onReady: (serverUrl: string) => void;
  initialUrl?: string;
}

export default function ServerSetup({ onReady, initialUrl = "" }: Props) {
  const [url, setUrl] = useState(initialUrl);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const normalized = normalizeServerUrl(url);
    if (!normalized) {
      setError("Enter your website address, e.g. https://yourdomain.com");
      setBusy(false);
      return;
    }
    try {
      const res = await fetch(`${normalized}/api/health`);
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      if (!data?.ok) throw new Error("This does not look like a VoxPersona server");
      setServerUrl(normalized);
      onReady(normalized);
    } catch (err) {
      setError(
        err instanceof Error
          ? `${err.message}. Check the URL and that your cPanel site is online (https).`
          : "Could not reach server",
      );
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
        <p className="brand-sub" style={{ marginBottom: "1.1rem" }}>
          Android app setup — enter the website where you hosted VoxPersona on
          cPanel (shared domain).
        </p>
        <form onSubmit={onSubmit}>
          <div className="field">
            <label>Server website URL</label>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://yourdomain.com"
              autoCapitalize="none"
              autoCorrect="off"
              inputMode="url"
              required
            />
          </div>
          <p className="status" style={{ marginBottom: "0.8rem" }}>
            Example: <code>{apiUrl("/api") || "https://voice.yourdomain.com"}</code>
          </p>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "Checking…" : "Connect & continue"}
          </button>
        </form>
        {error && <p className="status error" style={{ marginTop: "0.9rem" }}>{error}</p>}
      </div>
    </div>
  );
}
