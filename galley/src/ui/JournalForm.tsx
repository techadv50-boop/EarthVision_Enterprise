import { useState } from "react";
import type { IconAsset, Journal } from "../types";
import { newId } from "../metrics";
import { IconTray } from "./IconTray";

export function JournalForm({
  initial,
  onCancel,
  onSave,
}: {
  initial?: Journal;
  onCancel: () => void;
  onSave: (journal: Journal) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [abbreviation, setAbbreviation] = useState(initial?.abbreviation ?? "");
  const [issnP, setIssnP] = useState(initial?.issnP ?? "");
  const [issnE, setIssnE] = useState(initial?.issnE ?? "");
  const [partnerIcons, setPartnerIcons] = useState<IconAsset[]>(initial?.partnerIcons ?? []);
  const [error, setError] = useState("");

  return (
    <form
      className="panel form-stack"
      onSubmit={(event) => {
        event.preventDefault();
        if (!name.trim() || !abbreviation.trim()) {
          setError("Enter the journal name and its short abbreviation.");
          return;
        }
        onSave({
          id: initial?.id ?? newId(),
          name: name.trim(),
          abbreviation: abbreviation.trim(),
          issnP: issnP.trim(),
          issnE: issnE.trim(),
          topIcons: initial?.topIcons ?? [],
          partnerIcons,
        });
      }}
    >
      <header className="bar">
        <h1>{initial ? "Edit journal" : "Add journal"}</h1>
        <div className="bar-actions">
          <button type="button" className="ghost" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit">Save journal</button>
        </div>
      </header>
      <label>
        Full name
        <input value={name} onChange={(event) => setName(event.target.value)} required />
      </label>
      <label>
        Short abbreviation
        <input value={abbreviation} onChange={(event) => setAbbreviation(event.target.value)} required />
      </label>
      <div className="split">
        <label>
          ISSN-P
          <input value={issnP} onChange={(event) => setIssnP(event.target.value)} />
        </label>
        <label>
          ISSN-E
          <input value={issnE} onChange={(event) => setIssnE(event.target.value)} />
        </label>
      </div>
      <IconTray label="Partner icons" icons={partnerIcons} maxHeight={40} onChange={setPartnerIcons} />
      <p className="muted">These icons are stored with the journal. Every new galley for this journal starts with them.</p>
      {error && <p className="error">{error}</p>}
    </form>
  );
}
