import { useState } from "react";
import type { Galley } from "../types";
import { REFERENCE_STYLES, formattedReferences, segregateReferences } from "../references";
import { auditCitations, stitchBlocks } from "../citations";

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
  const audit = auditCitations(galley.blocks, galley.references);
  const stitch = (references = galley.references, referenceStyle = galley.referenceStyle) =>
    stitchBlocks(galley.blocks, references, referenceStyle);

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
              patch({ references, blocks: stitch(references, galley.referenceStyle) });
              setNotice(
                references.length
                  ? `Segregation completed. ${references.length} ${references.length === 1 ? "reference" : "references"}. Names and numbers in the text were stitched.`
                  : "Segregation completed. No references were found in that box.",
              );
              setBusy(false);
            }, 40);
          }}
        >
          {busy ? "Segregating…" : "Segregate"}
        </button>
        <p className="muted">
          Author, title, journal, volume, issue, pages, month, year, DOI, URL, publisher, and city are read for each reference. Nothing is left unattended.
        </p>
      </div>
      {notice && <p className="notice">{notice}</p>}
      <div className="style-box">
        <span className="style-label">Reference styles</span>
        <select
          aria-label="Reference styles"
          value={galley.referenceStyle}
          onChange={(event) => {
            const referenceStyle = event.target.value as Galley["referenceStyle"];
            patch({ referenceStyle, blocks: stitch(galley.references, referenceStyle) });
          }}
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
      <div className="tool-row">
        <button
          type="button"
          disabled={!galley.references.length}
          onClick={() => {
            patch({ blocks: stitch() });
            setNotice("Citations in the text were stitched to the segregated references.");
          }}
        >
          Stitch citations
        </button>
        <p className="muted">Names and years are matched to the segregated list. A number such as [1] is reference 1.</p>
      </div>
      <section className="report" aria-label="Citation report">
        <h2>Citation report</h2>
        <h3>In the text, not in the references</h3>
        {audit.missingInReferences.length === 0 ? (
          <p className="muted">Every name and number in the text matches a segregated reference.</p>
        ) : (
          <ul>
            {audit.missingInReferences.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        )}
        <h3>In the references, not cited in the text</h3>
        {audit.unusedReferences.length === 0 ? (
          <p className="muted">Every segregated reference is cited in the text.</p>
        ) : (
          <ul>
            {audit.unusedReferences.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}
