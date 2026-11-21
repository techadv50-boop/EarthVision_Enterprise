import { useState } from "react";
import { api, errorText } from "../api";
import { QuietButton } from "./ui";

export function SpeakButton({ text, language }: { text: string; language: string }) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <QuietButton
        disabled={busy || !text.trim()}
        onClick={() => {
          setBusy(true);
          setMessage("");
          void api.speak(text, language).then(setMessage).catch((err) => setMessage(errorText(err))).finally(() => setBusy(false));
        }}
      >
        {busy ? "Speaking…" : "Listen"}
      </QuietButton>
      {message ? <span className="text-sm text-muted">{message}</span> : null}
    </span>
  );
}
