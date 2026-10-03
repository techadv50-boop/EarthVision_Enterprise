import { useEffect, useState } from "react";
import { addUser, listUsers, setUserStatus, type Account, type GalleyRecord } from "../api";
import type { Journal } from "../types";

export function Admin({
  journals,
  archive,
  onDeleteJournal,
  onDeleteGalley,
  onAddJournal,
  onEditJournal,
  onOpenGalley,
  onBack,
}: {
  journals: Journal[];
  archive: GalleyRecord[];
  onDeleteJournal: (journal: Journal) => void;
  onDeleteGalley: (record: GalleyRecord) => void;
  onAddJournal: () => void;
  onEditJournal: (journal: Journal) => void;
  onOpenGalley: (record: GalleyRecord) => void;
  onBack: () => void;
}) {
  const [users, setUsers] = useState<Account[]>([]);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const refresh = () =>
    listUsers()
      .then(setUsers)
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : "Could not load users."));

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="panel">
      <header className="bar">
        <h1>Admin</h1>
        <button type="button" className="ghost" onClick={onBack}>
          Back to the desk
        </button>
      </header>
      {error && <p className="error">{error}</p>}

      <h2>Users</h2>
      <form
        className="split"
        onSubmit={async (event) => {
          event.preventDefault();
          setError("");
          try {
            await addUser(name, email, password);
            setName("");
            setEmail("");
            setPassword("");
            await refresh();
          } catch (caught) {
            setError(caught instanceof Error ? caught.message : "Could not add that user.");
          }
        }}
      >
        <label>
          Name
          <input value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label>
          Email
          <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={8} required />
        </label>
        <button type="submit">Add user</button>
      </form>
      <ul className="journal-list">
        {users.map((user) => (
          <li key={user.id}>
            <div className="journal-main">
              <strong>{user.name}</strong>
              <span>{user.email}</span>
              <small>
                {user.role} · {user.status}
              </small>
            </div>
            {user.role !== "admin" && (
              <div className="bar-actions">
                <button type="button" className="ghost" onClick={() => void change(user.id, "approved", setUsers, setError)}>
                  Approve
                </button>
                <button type="button" className="ghost" onClick={() => void change(user.id, "restricted", setUsers, setError)}>
                  Restrict
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>

      <h2>Journals</h2>
      <button type="button" onClick={onAddJournal}>
        + Add journal
      </button>
      <ul className="journal-list">
        {journals
          .slice()
          .sort((a, b) => a.name.localeCompare(b.name))
          .map((journal) => (
            <li key={journal.id}>
              <div className="journal-main">
                <strong>{journal.abbreviation}</strong>
                <span>{journal.name}</span>
              </div>
              <button type="button" className="ghost" onClick={() => onEditJournal(journal)}>
                Edit
              </button>
              <button type="button" className="ghost" onClick={() => onDeleteJournal(journal)}>
                Delete
              </button>
            </li>
          ))}
      </ul>

      <h2>Archive</h2>
      <p className="muted">Delete stays here. A composer can open a galley, and cannot remove it.</p>
      <ul className="journal-list">
        {archive.map((record) => {
          const journal = journals.find((item) => item.id === record.galley.journalId);
          return (
            <li key={record.galley.id}>
              <button type="button" className="journal-main" onClick={() => onOpenGalley(record)}>
                <strong>{journal?.abbreviation ?? "Journal"}</strong>
                <span>{record.galley.title.trim() || "Untitled galley"}</span>
                <small>
                  {record.ownerName} · {record.ownerEmail}
                </small>
              </button>
              <button type="button" className="ghost" onClick={() => onDeleteGalley(record)}>
                Delete
              </button>
            </li>
          );
        })}
        {archive.length === 0 && <li className="muted">No galley is in the archive yet.</li>}
      </ul>
    </div>
  );
}

async function change(
  id: string,
  status: Account["status"],
  setUsers: (users: Account[]) => void,
  setError: (message: string) => void,
) {
  setError("");
  try {
    await setUserStatus(id, status);
    setUsers(await listUsers());
  } catch (caught) {
    setError(caught instanceof Error ? caught.message : "Could not change that account.");
  }
}
