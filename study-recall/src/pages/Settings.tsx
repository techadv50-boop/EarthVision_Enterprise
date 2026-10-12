import { useEffect, useState, type FormEvent } from "react";
import { api, errorText, pickFile, pickSavePath } from "../api";
import { Field, Notice, PageHeader, PrimaryButton, QuietButton, inputClass } from "../components/ui";
import { useSession, useStudent } from "../store";
import type { BackupEntry, TrashItem } from "../types";

export function Settings() {
  const student = useStudent();
  const settings = useSession((state) => state.settings);
  const profiles = useSession((state) => state.profiles);
  const models = useSession((state) => state.models);
  const dataDirectory = useSession((state) => state.dataDirectory);
  const recovery = useSession((state) => state.recoveryPolicy);
  const refresh = useSession((state) => state.refresh);
  const applySettings = useSession((state) => state.applySettings);
  const applyModels = useSession((state) => state.applyModels);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("en");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [trash, setTrash] = useState<TrashItem[]>([]);
  const [history, setHistory] = useState<BackupEntry[]>([]);
  const [purge, setPurge] = useState<TrashItem | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [timers, setTimers] = useState({ mcq: "45", fib: "60", short: "240", long: "600", well: "80", developing: "50" });

  useEffect(() => {
    if (!settings) return;
    setTimers({
      mcq: String(settings.mcqSeconds),
      fib: String(settings.fibSeconds),
      short: String(settings.shortSeconds),
      long: String(settings.longSeconds),
      well: String(settings.wellRememberedPercent),
      developing: String(settings.developingPercent),
    });
  }, [settings]);

  useEffect(() => {
    if (!student) return;
    api.listTrash(student.id).then(setTrash).catch((err) => setError(errorText(err)));
    api.backupHistory().then(setHistory).catch(() => undefined);
  }, [student, message]);

  async function createProfile(event: FormEvent) {
    event.preventDefault();
    try {
      await api.createProfile(name, language);
      setName("");
      await refresh();
      setMessage("Student profile saved on this computer.");
      setError("");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function saveTimers(event: FormEvent) {
    event.preventDefault();
    try {
      const next = await api.updateSettings({
        mcqSeconds: Number(timers.mcq),
        fibSeconds: Number(timers.fib),
        shortSeconds: Number(timers.short),
        longSeconds: Number(timers.long),
        wellRememberedPercent: Number(timers.well),
        developingPercent: Number(timers.developing),
      });
      applySettings(next);
      setMessage("Timing and revision thresholds saved.");
      setError("");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function chooseModel(kind: "whisper" | "llama", which: "binary" | "model") {
    const current = models.find((model) => model.kind === kind);
    const selected = await pickFile();
    if (!selected || !current) return;
    try {
      const updated = await api.updateModel(
        kind,
        which === "binary" ? selected : current.binaryPath,
        which === "model" ? selected : current.modelPath,
      );
      applyModels(models.map((model) => (model.kind === kind ? updated : model)));
      setMessage(updated.statusMessage);
      setError("");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function backup() {
    const path = await pickSavePath("study-recall-backup.sqlite", [{ name: "SQLite", extensions: ["sqlite"] }]);
    if (!path) return;
    try {
      await api.backupDatabase(path);
      setMessage(`Backup written to ${path}.`);
      setHistory(await api.backupHistory());
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function restore() {
    const path = await pickFile([{ name: "SQLite", extensions: ["sqlite", "db"] }]);
    if (!path) return;
    if (!window.confirm("Restore replaces the current library after an integrity check. Continue?")) return;
    try {
      await api.restoreDatabase(path);
      await refresh();
      setMessage("Database restored from the selected backup.");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function exportJson() {
    const path = await pickSavePath("study-recall-export.json", [{ name: "JSON", extensions: ["json"] }]);
    if (!path) return;
    try {
      await api.exportJson(path);
      setMessage(`Export written to ${path}.`);
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function importJson() {
    const path = await pickFile([{ name: "JSON", extensions: ["json"] }]);
    if (!path) return;
    try {
      const count = await api.importJson(path);
      await refresh();
      setMessage(`Imported ${count} records as new copies. Existing notes were not erased.`);
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function restoreItem(item: TrashItem) {
    try {
      if (item.kind === "class") await api.restoreClass(item.id);
      if (item.kind === "book") await api.restoreBook(item.id);
      if (item.kind === "chapter") await api.restoreChapter(item.id);
      if (item.kind === "topic") await api.restoreTopic(item.id);
      setMessage(`${item.name} restored.`);
      if (student) setTrash(await api.listTrash(student.id));
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function purgeItem(event: FormEvent) {
    event.preventDefault();
    if (!purge) return;
    try {
      if (purge.kind === "class") await api.purgeClass(purge.id, confirmation);
      if (purge.kind === "book") await api.purgeBook(purge.id, confirmation);
      if (purge.kind === "chapter") await api.purgeChapter(purge.id, confirmation);
      if (purge.kind === "topic") await api.purgeTopic(purge.id, confirmation);
      setPurge(null);
      setConfirmation("");
      setMessage("The deleted item was removed permanently.");
      if (student) setTrash(await api.listTrash(student.id));
    } catch (err) {
      setError(errorText(err));
    }
  }

  const whisper = models.find((model) => model.kind === "whisper");
  const llama = models.find((model) => model.kind === "llama");

  return (
    <div className="space-y-8">
      <PageHeader title="Settings and backup" lede="Notes, recordings, and scores stay on this computer. No account is required." />
      {error ? <Notice tone="error">{error}</Notice> : null}
      {message ? <Notice tone="ok">{message}</Notice> : null}
      <section className="rounded-2xl border border-line bg-card p-5">
        <h2 className="text-xl font-semibold">Student profile</h2>
        {profiles.length > 0 ? (
          <label className="mt-3 block max-w-md text-sm">
            Active student
            <select
              className={`${inputClass} mt-1`}
              value={settings?.activeStudentId ?? ""}
              onChange={(event) => {
                void api.updateSettings({ activeStudentId: event.target.value }).then(async (next) => {
                  applySettings(next);
                  await refresh();
                }).catch((err) => setError(errorText(err)));
              }}
            >
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.displayName}</option>
              ))}
            </select>
          </label>
        ) : null}
        <form className="mt-4 grid gap-3 sm:grid-cols-[1fr_160px_auto]" onSubmit={(event) => void createProfile(event)}>
          <Field label="New student name">
            <input className={inputClass} value={name} onChange={(event) => setName(event.target.value)} required />
          </Field>
          <Field label="Preferred language">
            <select className={inputClass} value={language} onChange={(event) => setLanguage(event.target.value)}>
              <option value="en">English</option>
              <option value="ur">Urdu</option>
            </select>
          </Field>
          <div className="self-end"><PrimaryButton type="submit">Create profile</PrimaryButton></div>
        </form>
        {student ? (
          <form
            className="mt-4 flex flex-wrap items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              const form = event.currentTarget;
              const nextName = String(new FormData(form).get("rename") ?? "");
              void api.updateProfile(student.id, nextName, student.preferredLanguage).then(() => refresh()).then(() => setMessage("Profile renamed.")).catch((err) => setError(errorText(err)));
            }}
          >
            <Field label="Rename active student">
              <input className={inputClass} name="rename" defaultValue={student.displayName} />
            </Field>
            <QuietButton type="submit">Rename</QuietButton>
          </form>
        ) : null}
      </section>
      <form className="rounded-2xl border border-line bg-card p-5" onSubmit={(event) => void saveTimers(event)}>
        <h2 className="text-xl font-semibold">Examination timing</h2>
        <p className="mt-1 text-sm text-muted">Defaults are 45 seconds for multiple choice, 60 for blanks, 4 minutes for short answers, and 10 minutes for long answers.</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <NumberField label="Multiple choice seconds" value={timers.mcq} onChange={(value) => setTimers({ ...timers, mcq: value })} />
          <NumberField label="Fill-in-the-blank seconds" value={timers.fib} onChange={(value) => setTimers({ ...timers, fib: value })} />
          <NumberField label="Short question seconds" value={timers.short} onChange={(value) => setTimers({ ...timers, short: value })} />
          <NumberField label="Long question seconds" value={timers.long} onChange={(value) => setTimers({ ...timers, long: value })} />
          <NumberField label="Well remembered at or above (%)" value={timers.well} onChange={(value) => setTimers({ ...timers, well: value })} />
          <NumberField label="Developing at or above (%)" value={timers.developing} onChange={(value) => setTimers({ ...timers, developing: value })} />
        </div>
        <div className="mt-4"><PrimaryButton type="submit">Save timing</PrimaryButton></div>
      </form>
      <section className="rounded-2xl border border-line bg-card p-5">
        <h2 className="text-xl font-semibold">Offline speech and grading</h2>
        <p className="mt-1 text-sm text-muted">
          Whisper.cpp and llama.cpp run only if you select a local program and model file. Until then, you can type, and descriptive scores use the labeled approximate rubric.
        </p>
        <label className="mt-3 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={settings?.retainAudio ?? false}
            onChange={(event) => {
              void api.updateSettings({ retainAudio: event.target.checked }).then((next) => {
                applySettings(next);
                setMessage(next.retainAudio ? "Recordings will be kept after transcription." : "Recordings will be deleted after transcription.");
              }).catch((err) => setError(errorText(err)));
            }}
          />
          Keep recordings after a successful transcription
        </label>
        <ModelBlock
          title="Whisper.cpp"
          model={whisper}
          onBinary={() => void chooseModel("whisper", "binary")}
          onModel={() => void chooseModel("whisper", "model")}
        />
        <ModelBlock
          title="llama.cpp grading"
          model={llama}
          onBinary={() => void chooseModel("llama", "binary")}
          onModel={() => void chooseModel("llama", "model")}
        />
        <div className="mt-3">
          <QuietButton onClick={() => void api.refreshModels().then(applyModels).catch((err) => setError(errorText(err)))}>Check model files again</QuietButton>
        </div>
      </section>
      <section className="rounded-2xl border border-line bg-card p-5">
        <h2 className="text-xl font-semibold">Backup and restore</h2>
        <p className="mt-1 text-sm">Library file: {dataDirectory || "Not opened yet"}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <PrimaryButton onClick={() => void backup()}>Back up database</PrimaryButton>
          <QuietButton onClick={() => void restore()}>Restore database</QuietButton>
          <QuietButton onClick={() => void exportJson()}>Export JSON</QuietButton>
          <QuietButton onClick={() => void importJson()}>Import JSON</QuietButton>
          <QuietButton onClick={() => void api.integrityCheck().then((result) => setMessage(`Integrity check: ${result}`)).catch((err) => setError(errorText(err)))}>
            Check database
          </QuietButton>
        </div>
        <p className="mt-3 text-sm text-muted">JSON import adds records as new copies. It does not delete the notes already stored.</p>
        {history.length > 0 ? (
          <ul className="mt-3 space-y-1 text-sm">
            {history.map((entry) => (
              <li key={entry.id}>{entry.createdAt} · {entry.action} · {entry.status} · {entry.message}</li>
            ))}
          </ul>
        ) : null}
      </section>
      <section className="rounded-2xl border border-line bg-card p-5">
        <h2 className="text-xl font-semibold">Recently deleted</h2>
        {trash.length === 0 ? <p className="mt-2 text-sm text-muted">Nothing is waiting to be restored.</p> : null}
        <ul className="mt-3 space-y-2">
          {trash.map((item) => (
            <li key={`${item.kind}-${item.id}`} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line px-3 py-2">
              <span>{item.kind}: {item.name} <span className="text-sm text-muted">{item.parentLabel}</span></span>
              <span className="flex gap-2">
                <QuietButton onClick={() => void restoreItem(item)}>Restore</QuietButton>
                <QuietButton onClick={() => { setPurge(item); setConfirmation(""); }}>Remove permanently</QuietButton>
              </span>
            </li>
          ))}
        </ul>
        {purge ? (
          <form className="mt-4" onSubmit={(event) => void purgeItem(event)}>
            <p className="text-sm">Type DELETE to permanently remove “{purge.name}”.</p>
            <div className="mt-2 flex gap-2">
              <input className={inputClass} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} aria-label="Type DELETE" />
              <PrimaryButton type="submit">Remove</PrimaryButton>
              <QuietButton onClick={() => setPurge(null)}>Cancel</QuietButton>
            </div>
          </form>
        ) : null}
      </section>
      <section className="rounded-2xl border border-line bg-card p-5 text-sm text-muted">
        <h2 className="text-base font-semibold text-ink">If an examination is interrupted</h2>
        <p className="mt-2">{recovery}</p>
      </section>
    </div>
  );
}

function NumberField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <Field label={label}>
      <input className={inputClass} inputMode="decimal" value={value} onChange={(event) => onChange(event.target.value)} />
    </Field>
  );
}

function ModelBlock({
  title,
  model,
  onBinary,
  onModel,
}: {
  title: string;
  model?: { available: boolean; statusMessage: string; binaryPath: string; modelPath: string };
  onBinary: () => void;
  onModel: () => void;
}) {
  return (
    <div className="mt-4 rounded-xl border border-line p-3">
      <h3 className="font-semibold">{title}</h3>
      <p className="mt-1 text-sm">{model?.statusMessage}</p>
      <p className="mt-1 text-xs text-muted">Program: {model?.binaryPath || "Not selected"}</p>
      <p className="text-xs text-muted">Model: {model?.modelPath || "Not selected"}</p>
      <div className="mt-2 flex gap-2">
        <QuietButton onClick={onBinary}>Choose program</QuietButton>
        <QuietButton onClick={onModel}>Choose model file</QuietButton>
      </div>
    </div>
  );
}
