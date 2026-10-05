import { useState } from "react";
import type { Galley, IconAsset, Journal } from "../types";
import { displayFigureCaption, displayTableCaption, flowBody, parseStartPage, figureNumber, tableNumber } from "../metrics";
import { composedBlocks } from "../references";
import { FrontSheet, SheetFooter, SheetHeader } from "./FirstPage";
import { EquationView } from "./EquationView";
import { parseMath } from "../equations";
import { columnWidths, sanitizeTableRows } from "../tables";
import type { BodyBlock } from "../types";

export function Proof({
  galley,
  journal,
  openAccess,
  onBack,
}: {
  galley: Galley;
  journal: Journal;
  openAccess: IconAsset | null;
  onBack: () => void;
}) {
  const start = parseStartPage(galley.startPage);
  const pages = flowBody(composedBlocks(galley));
  const [index, setIndex] = useState(0);
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const selected = index === 0 ? "front" : pages[index - 1];

  return (
    <div className="panel">
      <header className="bar">
        <h1>Proof</h1>
        <div className="bar-actions">
          <button type="button" className="ghost" onClick={onBack}>
            Back to body
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={async () => {
              if (!start) {
                setMessage("Enter the starting page number on the first page before saving the Word file.");
                return;
              }
              setSaving(true);
              setMessage("");
              try {
                const [{ Packer }, { galleyDocument, suggestedFileName }] = await Promise.all([
                  import("docx"),
                  import("../exportDocx"),
                ]);
                const fileName = suggestedFileName(journal, galley);
                const blob = await Packer.toBlob(galleyDocument(galley, journal, openAccess));
                const url = URL.createObjectURL(blob);
                const link = document.createElement("a");
                link.href = url;
                link.download = fileName;
                link.click();
                URL.revokeObjectURL(url);
                setMessage(`Saved ${fileName}`);
              } catch (error) {
                setMessage(error instanceof Error ? error.message : "Could not write the Word file.");
              } finally {
                setSaving(false);
              }
            }}
          >
            Save Word document
          </button>
        </div>
      </header>
      {!start && <p className="error">The starting page number is required. Manuscripts do not begin at page 1 unless you enter 1.</p>}
      {message && <p className="muted">{message}</p>}
      <div className="thumbs">
        <button type="button" className={index === 0 ? "thumb on" : "thumb"} onClick={() => setIndex(0)}>
          Page {start ?? "—"}
          <small>first page</small>
        </button>
        {pages.map((page, pageIndex) => {
          const number = start ? start + pageIndex + 1 : pageIndex + 2;
          return (
            <button
              key={pageIndex}
              type="button"
              className={index === pageIndex + 1 ? "thumb on" : "thumb"}
              onClick={() => setIndex(pageIndex + 1)}
            >
              Page {number}
              <small>{page.kind === "landscape" ? "landscape" : "7.5 × 10"}</small>
            </button>
          );
        })}
      </div>
      <div className="proof-stage">
        {selected === "front" || !selected ? (
          <FrontSheet galley={galley} journal={journal} openAccess={openAccess} />
        ) : selected.kind === "landscape" ? (
          <div className="sheet-frame wide" style={{ height: "3.75in" }}>
          <article className="sheet landscape">
            <SheetHeader journal={journal} openAccess={openAccess} />
            <p className="caption">{displayTableCaption(selected.block.caption, tableNumber(galley.blocks, selected.block.id))}</p>
        <table>
          <colgroup>
            {columnWidths(sanitizeTableRows(selected.block.rows)).map((width, index) => (
              <col key={index} style={{ width: `${width}%` }} />
            ))}
          </colgroup>
          <tbody>
                {sanitizeTableRows(selected.block.rows).map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((cell, column) => (
                      <td key={column}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <SheetFooter galley={galley} page={start ? start + index : "—"} />
          </article>
          </div>
        ) : (
          <div className="sheet-frame" style={{ height: "5in" }}>
          <article className="sheet body-sheet">
            <SheetHeader journal={journal} openAccess={openAccess} />
            <div className="body-copy">
              {selected.blocks.map((block) => (
                <ProofBlock key={block.id} block={block} galley={galley} />
              ))}
            </div>
            <SheetFooter galley={galley} page={start ? start + index : "—"} />
          </article>
          </div>
        )}
      </div>
    </div>
  );
}

function ProofBlock({ block, galley }: { block: BodyBlock; galley: Galley }) {
  if (block.type === "heading") return <p className="heading-line">{block.text}</p>;
  if (block.type === "section") {
    return (
      <>
        {block.heading && <p className="heading-line">{block.heading}</p>}
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
        <figcaption>{displayFigureCaption(block.caption, figureNumber(galley.blocks, block.id))}</figcaption>
      </figure>
    );
  }
  if (block.type === "table") {
    return (
      <div>
        <p className="caption">{displayTableCaption(block.caption, tableNumber(galley.blocks, block.id))}</p>
        <table>
          <colgroup>
            {columnWidths(sanitizeTableRows(block.rows)).map((width, index) => (
              <col key={index} style={{ width: `${width}%` }} />
            ))}
          </colgroup>
          <tbody>
            {sanitizeTableRows(block.rows).map((row, rowIndex) => (
              <tr key={rowIndex}>
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
    return <EquationView atoms={block.source ? parseMath(block.source) : block.atoms} number={block.number} />;
  }
  return null;
}
