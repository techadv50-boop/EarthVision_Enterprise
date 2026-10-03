import { useState } from "react";
import type { BodyBlock, EquationAtom, EquationBlock, Galley, IconAsset, Journal, TableBlock } from "../types";
import { figureNumber, flowBody, newId, parseStartPage, tableNumber } from "../metrics";
import { composedBlocks } from "../references";
import { fileToDataUrl } from "../storage";
import { atomsFromOcr } from "../equations";
import { parseTable } from "../tables";
import { readEquation } from "../api";
import { SheetFooter, SheetHeader } from "./FirstPage";
import { ReferencesPanel } from "./ReferencesPanel";
import { EquationView } from "./EquationView";

export function BodyDesk({
  galley,
  journal,
  openAccess,
  onChange,
  onBack,
  onProof,
}: {
  galley: Galley;
  journal: Journal;
  openAccess: IconAsset | null;
  onChange: (galley: Galley) => void;
  onBack: () => void;
  onProof: () => void;
}) {
  const setBlocks = (blocks: BodyBlock[]) => onChange({ ...galley, blocks, updatedAt: Date.now() });
  const update = (id: string, block: BodyBlock) => setBlocks(galley.blocks.map((item) => (item.id === id ? block : item)));
  const insert = (block: BodyBlock) => setBlocks([...galley.blocks, block]);
  const start = parseStartPage(galley.startPage);
  const pages = flowBody(composedBlocks(galley));
  const firstPortrait = pages.find((page) => page.kind === "portrait");

  return (
    <div className="desk">
      <header className="bar">
        <h1>{journal.abbreviation} · body</h1>
        <div className="bar-actions">
          <button type="button" className="ghost" onClick={onBack}>
            Back to first page
          </button>
          <button type="button" onClick={onProof}>
            Open proof
          </button>
        </div>
      </header>
      <div className="desk-grid">
        <div className="form-stack">
          <div className="tool-row">
            <button
              type="button"
              className="plus"
              aria-label="Add heading and paragraph"
              onClick={() => insert({ id: newId(), type: "section", heading: "", text: "" })}
            >
              +
            </button>
            <span className="muted">Add a heading and its paragraph</span>
            <button
              type="button"
              onClick={() => insert({ id: newId(), type: "figure", dataUrl: "", widthPx: 0, heightPx: 0, caption: "" })}
            >
              Figure
            </button>
            <button
              type="button"
              onClick={() => insert({ id: newId(), type: "table", caption: "", source: "", rows: [], landscape: false })}
            >
              Table
            </button>
            <button type="button" onClick={() => insert({ id: newId(), type: "equation", imageUrl: "", atoms: [], number: "" })}>
              Equation
            </button>
          </div>
          {galley.blocks.map((block) => (
            <article key={block.id} className="block">
              <div className="block-tools">
                <span>{block.type === "pageBreak" ? "Page break" : block.type}</span>
                <button
                  type="button"
                  className="ghost"
                  onClick={() => setBlocks(galley.blocks.filter((item) => item.id !== block.id))}
                >
                  Remove
                </button>
              </div>
              {block.type === "section" && (
                <>
                  <label>
                    Heading
                    <input
                      value={block.heading}
                      onChange={(event) => update(block.id, { ...block, heading: event.target.value })}
                    />
                  </label>
                  <label>
                    Paragraph
                    <textarea
                      rows={6}
                      value={block.text}
                      onChange={(event) => update(block.id, { ...block, text: event.target.value })}
                    />
                  </label>
                </>
              )}
              {block.type === "heading" && (
                <input value={block.text} onChange={(event) => update(block.id, { ...block, text: event.target.value })} />
              )}
              {block.type === "paragraph" && (
                <textarea
                  rows={5}
                  value={block.text}
                  onChange={(event) => update(block.id, { ...block, text: event.target.value })}
                />
              )}
              {block.type === "figure" && (
                <>
                  <div
                    className="drop-box"
                    tabIndex={0}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={async (event) => {
                      event.preventDefault();
                      const file = [...event.dataTransfer.files].find((item) => item.type.startsWith("image/"));
                      if (!file) return;
                      const dataUrl = await fileToDataUrl(file);
                      const size = await measure(dataUrl);
                      update(block.id, { ...block, dataUrl, widthPx: size.width, heightPx: size.height });
                    }}
                    onPaste={async (event) => {
                      const file = imageFromClipboard(event.clipboardData);
                      if (!file) return;
                      event.preventDefault();
                      const dataUrl = await fileToDataUrl(file);
                      const size = await measure(dataUrl);
                      update(block.id, { ...block, dataUrl, widthPx: size.width, heightPx: size.height });
                    }}
                  >
                    <p>Click this box and paste the figure. Uploading a saved file is optional.</p>
                    <textarea rows={2} aria-label="Paste figure" placeholder="Paste the figure here" readOnly />
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/gif,image/webp"
                      aria-label="Figure image"
                      onChange={async (event) => {
                        const file = event.target.files?.[0];
                        if (!file) return;
                        const dataUrl = await fileToDataUrl(file);
                        const size = await measure(dataUrl);
                        update(block.id, { ...block, dataUrl, widthPx: size.width, heightPx: size.height });
                      }}
                    />
                    {block.dataUrl && <img className="figure-thumb" src={block.dataUrl} alt="" />}
                  </div>
                  <label>
                    Caption
                    <input
                      value={block.caption}
                      onChange={(event) => update(block.id, { ...block, caption: event.target.value })}
                    />
                  </label>
                </>
              )}
              {block.type === "table" && <TablePaste block={block} onChange={(next) => update(block.id, next)} />}
              {block.type === "equation" && <EquationCard block={block} onChange={(next) => update(block.id, next)} />}
              {block.type === "pageBreak" && <p className="muted">The next block starts on a fresh 7.5 × 10 inch page.</p>}
            </article>
          ))}
          <ReferencesPanel galley={galley} onChange={onChange} />
        </div>
        <aside className="preview-column">
          <p className="muted">Page 2 onward · 7.5 × 10 in</p>
          {pages.some((page) => page.kind === "landscape") && (
            <p className="muted">A landscape page is inserted on its own, then the next page returns to portrait.</p>
          )}
          <div className="sheet-frame" style={{ height: "5in" }}>
            <article className="sheet body-sheet">
              <SheetHeader journal={journal} openAccess={openAccess} />
              <div className="body-copy">
                {(firstPortrait && firstPortrait.kind === "portrait" ? firstPortrait.blocks : []).map((block) => (
                  <BlockPreview key={block.id} block={block} galley={galley} />
                ))}
              </div>
              <SheetFooter galley={galley} page={start ? start + 1 : "—"} />
            </article>
          </div>
        </aside>
      </div>
    </div>
  );
}

function BlockPreview({ block, galley }: { block: BodyBlock; galley: Galley }) {
  if (block.type === "heading") return <p className="heading-line">{block.text}</p>;
  if (block.type === "section") {
    return (
      <>
        {block.heading && <p className="heading-line">{block.heading.endsWith(":") ? block.heading : `${block.heading}:`}</p>}
        {block.text && <p className="indent">{block.text}</p>}
      </>
    );
  }
  if (block.type === "referenceLine") return <p>{block.text}</p>;
  if (block.type === "paragraph") return <p className="indent">{block.text}</p>;
  if (block.type === "figure") {
    return (
      <figure>
        {block.dataUrl && <img src={block.dataUrl} alt="" />}
        <figcaption>
          <strong>Figure {figureNumber(galley.blocks, block.id)}. </strong>
          {block.caption}
        </figcaption>
      </figure>
    );
  }
  if (block.type === "table") {
    return (
      <div>
        <p className="caption">
          <strong>Table {tableNumber(galley.blocks, block.id)}. </strong>
          {block.caption}
          {block.landscape ? " (landscape page)" : ""}
        </p>
        <table>
          <tbody>
            {block.rows.map((row, index) => (
              <tr key={index}>
                {row.map((cell, column) => (
                  <td key={column}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (block.type === "equation") return <EquationView atoms={block.atoms} number={block.number} />;
  return null;
}

function TablePaste({ block, onChange }: { block: TableBlock; onChange: (block: TableBlock) => void }) {
  const apply = (raw: string) => {
    const rows = parseTable(raw);
    const source = rows.length ? rows.map((row) => row.join("\t")).join("\n") : raw;
    onChange({ ...block, source, rows });
  };
  return (
    <>
      <label>
        Caption
        <input value={block.caption} onChange={(event) => onChange({ ...block, caption: event.target.value })} />
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={block.landscape}
          onChange={(event) => onChange({ ...block, landscape: event.target.checked })}
        />
        Landscape page
      </label>
      <p className="muted">
        Pages stay portrait. Checking this places the table on its own landscape page and inserts the page break and section break around it.
      </p>
      <label>
        Paste the table
        <textarea
          rows={8}
          value={block.source}
          placeholder="Paste a table from Word, Excel, or a web page"
          onPaste={(event) => {
            const html = event.clipboardData.getData("text/html");
            const text = event.clipboardData.getData("text/plain");
            const raw = html && /<table[\s>]/i.test(html) ? html : text;
            if (!raw.trim()) return;
            event.preventDefault();
            apply(raw);
          }}
          onChange={(event) => apply(event.target.value)}
        />
      </label>
      {block.rows.length > 0 && (
        <table className="pasted">
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, column) => (
                  <td key={column}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function EquationCard({ block, onChange }: { block: EquationBlock; onChange: (block: EquationBlock) => void }) {
  const [note, setNote] = useState("");

  const take = async (file: File) => {
    const imageUrl = await fileToDataUrl(file);
    onChange({ ...block, imageUrl });
    try {
      const { text } = await readEquation(imageUrl);
      onChange({ ...block, imageUrl, atoms: atomsFromOcr(text) });
      setNote(text ? `Read as: ${text}` : "No text was read. Type the parts below.");
    } catch (error) {
      setNote(error instanceof Error ? `${error.message} You can still type the parts.` : "You can still type the parts.");
    }
  };

  const setAtom = (index: number, atom: EquationAtom) => {
    const atoms = block.atoms.slice();
    atoms[index] = atom;
    onChange({ ...block, atoms });
  };

  return (
    <>
      <div
        className="drop-box"
        tabIndex={0}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          const file = [...event.dataTransfer.files].find((item) => item.type.startsWith("image/"));
          if (file) void take(file);
        }}
        onPaste={(event) => {
          const file = imageFromClipboard(event.clipboardData);
          if (file) {
            event.preventDefault();
            void take(file);
            return;
          }
          const text = event.clipboardData.getData("text/plain").trim();
          if (!text) return;
          event.preventDefault();
          onChange({ ...block, atoms: atomsFromOcr(text) });
          setNote("Pasted as text. Edit the parts below.");
        }}
      >
        <p>Click this box and paste the equation image or its text. Uploading a saved file is optional.</p>
        <textarea rows={2} aria-label="Paste equation" placeholder="Paste the equation here" readOnly />
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp"
          aria-label="Equation image"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void take(file);
          }}
        />
        {block.imageUrl && <img className="figure-thumb" src={block.imageUrl} alt="Equation snapshot" />}
      </div>
      {note && <p className="muted">{note}</p>}
      <EquationView atoms={block.atoms} number={block.number} />
      {block.atoms.map((atom, index) => (
        <div key={index} className="atom-row">
          {atom.kind === "frac" ? (
            <>
              <label>
                Numerator
                <input value={atom.num} onChange={(event) => setAtom(index, { ...atom, num: event.target.value })} />
              </label>
              <label>
                Denominator
                <input value={atom.den} onChange={(event) => setAtom(index, { ...atom, den: event.target.value })} />
              </label>
            </>
          ) : (
            <label>
              {atom.kind === "sup" ? "Superscript" : atom.kind === "sub" ? "Subscript" : "Text"}
              <input
                aria-label={atom.kind === "sup" ? "Superscript" : atom.kind === "sub" ? "Subscript" : "Equation text"}
                placeholder={atom.kind === "text" && atom.value.trim() === "" ? "space" : undefined}
                value={atom.value}
                onChange={(event) => setAtom(index, { ...atom, value: event.target.value })}
              />
            </label>
          )}
          <button
            type="button"
            className="ghost"
            onClick={() => onChange({ ...block, atoms: block.atoms.filter((_, atomIndex) => atomIndex !== index) })}
          >
            Remove part
          </button>
        </div>
      ))}
      <div className="tool-row">
        <button type="button" className="ghost" onClick={() => onChange({ ...block, atoms: [...block.atoms, { kind: "text", value: "" }] })}>
          Text
        </button>
        <button type="button" className="ghost" onClick={() => onChange({ ...block, atoms: [...block.atoms, { kind: "sup", value: "" }] })}>
          Superscript
        </button>
        <button type="button" className="ghost" onClick={() => onChange({ ...block, atoms: [...block.atoms, { kind: "sub", value: "" }] })}>
          Subscript
        </button>
        <button
          type="button"
          className="ghost"
          onClick={() => onChange({ ...block, atoms: [...block.atoms, { kind: "frac", num: "", den: "" }] })}
        >
          Ratio line
        </button>
      </div>
      <label>
        Number
        <input value={block.number} onChange={(event) => onChange({ ...block, number: event.target.value })} />
      </label>
    </>
  );
}

function imageFromClipboard(data: DataTransfer): File | null {
  const direct = [...data.files].find((item) => item.type.startsWith("image/"));
  if (direct) return direct;
  for (const item of data.items) {
    if (item.type.startsWith("image/")) return item.getAsFile();
  }
  return null;
}

function measure(dataUrl: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
    image.onerror = () => resolve({ width: 480, height: 280 });
    image.src = dataUrl;
  });
}
