import type { Galley, ReferenceItem, ReferenceKind } from "../types";
import { REFERENCE_STYLES, emptyReference, formatReference, parseReference } from "../references";

const KINDS: { id: ReferenceKind; label: string }[] = [
  { id: "journal", label: "Journal" },
  { id: "book", label: "Book" },
  { id: "conference", label: "Conference" },
];

export function ReferencesPanel({
  galley,
  onChange,
}: {
  galley: Galley;
  onChange: (galley: Galley) => void;
}) {
  const patch = (partial: Partial<Galley>) => onChange({ ...galley, ...partial, updatedAt: Date.now() });
  const update = (item: ReferenceItem) =>
    patch({ references: galley.references.map((current) => (current.id === item.id ? item : current)) });

  return (
    <section className="references">
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
      <div className="bar">
        <h2>References</h2>
        <button type="button" className="plus" aria-label="Add reference" onClick={() => patch({ references: [...galley.references, emptyReference()] })}>
          +
        </button>
      </div>
      <p className="muted">Paste one reference, then read its fields. Changing the style rewrites every reference.</p>
      {galley.references.map((item, index) => (
        <article key={item.id} className="block">
          <div className="block-tools">
            <span>Reference {index + 1}</span>
            <button
              type="button"
              className="ghost"
              onClick={() => patch({ references: galley.references.filter((current) => current.id !== item.id) })}
            >
              Remove
            </button>
          </div>
          <label>
            Paste reference
            <textarea rows={3} value={item.raw} onChange={(event) => update({ ...item, raw: event.target.value })} />
          </label>
          <button type="button" className="ghost" onClick={() => update({ ...parseReference(item.raw), id: item.id })}>
            Read fields
          </button>
          <label>
            Type
            <select value={item.kind} onChange={(event) => update({ ...item, kind: event.target.value as ReferenceKind })}>
              {KINDS.map((kind) => (
                <option key={kind.id} value={kind.id}>
                  {kind.label}
                </option>
              ))}
            </select>
          </label>
          <div className="split">
            <label>
              Authors
              <input value={item.authors} onChange={(event) => update({ ...item, authors: event.target.value })} />
            </label>
            <label>
              Year
              <input value={item.year} onChange={(event) => update({ ...item, year: event.target.value })} />
            </label>
          </div>
          <label>
            Title
            <input value={item.title} onChange={(event) => update({ ...item, title: event.target.value })} />
          </label>
          <label>
            {item.kind === "book" ? "Series or edition" : item.kind === "conference" ? "Conference" : "Journal"}
            <input value={item.container} onChange={(event) => update({ ...item, container: event.target.value })} />
          </label>
          <div className="split">
            <label>
              Volume
              <input value={item.volume} onChange={(event) => update({ ...item, volume: event.target.value })} />
            </label>
            <label>
              Issue
              <input value={item.issue} onChange={(event) => update({ ...item, issue: event.target.value })} />
            </label>
            <label>
              Pages
              <input value={item.pages} onChange={(event) => update({ ...item, pages: event.target.value })} />
            </label>
          </div>
          <div className="split">
            <label>
              Publisher
              <input value={item.publisher} onChange={(event) => update({ ...item, publisher: event.target.value })} />
            </label>
            <label>
              City
              <input value={item.city} onChange={(event) => update({ ...item, city: event.target.value })} />
            </label>
            <label>
              DOI
              <input value={item.doi} onChange={(event) => update({ ...item, doi: event.target.value })} />
            </label>
          </div>
          <p className="citation-line">{formatReference(item, galley.referenceStyle, index + 1)}</p>
        </article>
      ))}
    </section>
  );
}
