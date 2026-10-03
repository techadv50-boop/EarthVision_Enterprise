import type { BodyBlock, Galley, IconAsset, Journal } from "../types";
import { figureNumber, flowBody, newId, parseStartPage, tableNumber } from "../metrics";
import { fileToDataUrl } from "../storage";
import { SheetFooter, SheetHeader } from "./FirstPage";

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
  const pages = flowBody(galley.blocks);
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
            <button type="button" onClick={() => insert({ id: newId(), type: "heading", text: "Heading:" })}>
              Heading
            </button>
            <button type="button" onClick={() => insert({ id: newId(), type: "paragraph", text: "" })}>
              Paragraph
            </button>
            <button
              type="button"
              onClick={() => insert({ id: newId(), type: "figure", dataUrl: "", widthPx: 0, heightPx: 0, caption: "" })}
            >
              Figure
            </button>
            <button
              type="button"
              onClick={() =>
                insert({
                  id: newId(),
                  type: "table",
                  caption: "",
                  landscape: false,
                  rows: [
                    ["", ""],
                    ["", ""],
                  ],
                })
              }
            >
              Table
            </button>
            <button type="button" onClick={() => insert({ id: newId(), type: "equation", text: "", number: "" })}>
              Equation
            </button>
            <button type="button" onClick={() => insert({ id: newId(), type: "pageBreak" })}>
              Page break
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
                  <label>
                    Caption
                    <input
                      value={block.caption}
                      onChange={(event) => update(block.id, { ...block, caption: event.target.value })}
                    />
                  </label>
                </>
              )}
              {block.type === "table" && (
                <>
                  <label>
                    Caption
                    <input
                      value={block.caption}
                      onChange={(event) => update(block.id, { ...block, caption: event.target.value })}
                    />
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={block.landscape}
                      onChange={(event) => update(block.id, { ...block, landscape: event.target.checked })}
                    />
                    This table needs a landscape page
                  </label>
                  <div className="table-edit">
                    {block.rows.map((row, rowIndex) => (
                      <div key={rowIndex} className="table-row">
                        {row.map((cell, column) => (
                          <input
                            key={column}
                            value={cell}
                            aria-label={`Row ${rowIndex + 1} column ${column + 1}`}
                            onChange={(event) => {
                              const rows = block.rows.map((line) => line.slice());
                              rows[rowIndex][column] = event.target.value;
                              update(block.id, { ...block, rows });
                            }}
                          />
                        ))}
                      </div>
                    ))}
                    <div className="tool-row">
                      <button
                        type="button"
                        className="ghost"
                        onClick={() => update(block.id, { ...block, rows: [...block.rows, block.rows[0].map(() => "")] })}
                      >
                        Add row
                      </button>
                      <button
                        type="button"
                        className="ghost"
                        onClick={() =>
                          update(block.id, { ...block, rows: block.rows.map((row) => [...row, ""]) })
                        }
                      >
                        Add column
                      </button>
                    </div>
                  </div>
                </>
              )}
              {block.type === "equation" && (
                <div className="split">
                  <label>
                    Equation
                    <input value={block.text} onChange={(event) => update(block.id, { ...block, text: event.target.value })} />
                  </label>
                  <label>
                    Number
                    <input
                      value={block.number}
                      onChange={(event) => update(block.id, { ...block, number: event.target.value })}
                    />
                  </label>
                </div>
              )}
              {block.type === "pageBreak" && <p className="muted">The next block starts on a fresh 7.5 × 10 inch page.</p>}
            </article>
          ))}
        </div>
        <aside className="preview-column">
          <p className="muted">Page 2 onward · 7.5 × 10 in</p>
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
  if (block.type === "equation") {
    return (
      <p className="caption">
        {block.text} {block.number && `(${block.number})`}
      </p>
    );
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
