import { useMemo, useState } from "react";
import type { Galley, Journal } from "../types";

export function Shelf({
  journals,
  galleys,
  accountName,
  isAdmin,
  onOpenJournal,
  onOpenGalley,
  onAdmin,
  onLogout,
}: {
  journals: Journal[];
  galleys: Galley[];
  accountName: string;
  isAdmin: boolean;
  onOpenJournal: (journal: Journal) => void;
  onOpenGalley: (galley: Galley) => void;
  onAdmin: () => void;
  onLogout: () => void;
}) {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return journals
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .filter((journal) => {
        if (!needle) return true;
        return (
          journal.name.toLowerCase().includes(needle) || journal.abbreviation.toLowerCase().includes(needle)
        );
      });
  }, [journals, query]);

  return (
    <div className="panel">
      <header className="bar">
        <div>
          <h1>Galley</h1>
          <p className="muted">galley.drxdhr.com</p>
        </div>
        <div className="bar-actions">
          <span className="muted">{accountName}</span>
          {isAdmin && (
            <button type="button" onClick={onAdmin}>
              Admin
            </button>
          )}
          <button type="button" className="ghost" onClick={onLogout}>
            Sign out
          </button>
        </div>
      </header>
      <label className="search">
        Search journals
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Name or abbreviation" />
      </label>
      <ul className="journal-list">
        {shown.map((journal) => (
          <li key={journal.id}>
            <button type="button" className="journal-main" onClick={() => onOpenJournal(journal)}>
              <strong>{journal.abbreviation}</strong>
              <span>{journal.name}</span>
              <small>
                {journal.partnerIcons.length} partner icons
                {journal.issnP ? ` · ISSN-P ${journal.issnP}` : ""}
                {journal.issnE ? ` · ISSN-E ${journal.issnE}` : ""}
              </small>
            </button>
          </li>
        ))}
        {shown.length === 0 && <li className="muted">No journal matches that search.</li>}
      </ul>
      <h2>Saved galleys</h2>
      <ul className="journal-list">
        {galleys
          .slice()
          .sort((a, b) => b.updatedAt - a.updatedAt)
          .map((galley) => {
            const journal = journals.find((item) => item.id === galley.journalId);
            return (
              <li key={galley.id}>
                <button type="button" className="journal-main" onClick={() => onOpenGalley(galley)}>
                  <strong>{journal?.abbreviation ?? "Journal"}</strong>
                  <span>{galley.title.trim() || "Untitled galley"}</span>
                </button>
              </li>
            );
          })}
        {galleys.length === 0 && <li className="muted">A galley you save will stay in this list.</li>}
      </ul>
    </div>
  );
}
