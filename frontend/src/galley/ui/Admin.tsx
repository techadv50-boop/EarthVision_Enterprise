import { Link } from "react-router-dom";
import type { GalleyRecord } from "../api";
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
  return (
    <div className="panel">
      <header className="bar">
        <h1>Admin</h1>
        <button type="button" className="ghost" onClick={onBack}>
          Back to the desk
        </button>
      </header>
      <p className="muted">
        Accounts stay on Admin → Adding users so composers keep one username and password.{" "}
        <Link to="/admin">Open Admin desks</Link>
      </p>

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
