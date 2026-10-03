import { useState } from "react";
import type { Galley } from "../types";
import { REFERENCE_STYLES, formattedReferences, segregateReferences } from "../references";

export function ReferencesPanel({
  galley,
  onChange,
}: {
  galley: Galley;
  onChange: (galley: Galley) => void;
}) {
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const patch = (partial: Partial<Galley>) => onChange({ ...galley, ...partial, updatedAt: Date.now() });
  const segregated = formattedReferences(galley).join("\n\n");

  return (
    <section className="references">
      <div className="bar">
        <h2>References</h2>
      </div>
      <label>
        Original references
        <textarea
          rows={12}
          aria-label="Original references"
          placeholder="Paste every reference here, one after another"
          value={galley.referenceSource}
          onChange={(event) => {
            setNotice("");
            patch({ referenceSource: event.target.value });
          }}
        />
      </label>
      <div className="tool-row">
        <button
          type="button"
          disabled={busy || !galley.referenceSource.trim()}
          onClick={() => {
            setBusy(true);
            setNotice("");
            window.setTimeout(() => {
              const references = segregateReferences(galley.referenceSource);
              patch({ references });
              setNotice(
                references.length
                  ? `Segregation completed. ${references.length} ${references.length === 1 ? "reference" : "references"}.`
                  : "Segregation completed. No references were found in that box.",
              );
              setBusy(false);
            }, 40);
          }}
        >
          {busy ? "Segregating…" : "Segregate"}
        </button>
        <p className="muted">Author, title, journal, month, issue, volume, pages, URL, and DOI are read for each reference.</p>
      </div>
      {notice && <p className="notice">{notice}</p>}
      <div className="style-box">
        <span className="style-label">Reference styles</span>
        <select
          aria-label="Reference styles"
          value={galley.referenceStyle}
          onChange={(event) => patch({ referenceStyle: event.target.value as Galley["referenceStyle"] })}
        >
          {REFERENCE_STYLES.map((style) => (
            <option key={style.id} value={style.id}>
              {style.label}
            </option>
          ))}
        </select>
      </div>
      <label>
        Segregated references
        <textarea rows={12} aria-label="Segregated references" readOnly value={segregated} />
      </label>
    </section>
  );
}
