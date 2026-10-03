import type { Galley, IconAsset, Journal } from "../types";
import {
  buildCitation,
  dateLine,
  endPageNumber,
  firstPageHeightInches,
  flowBody,
  numberAuthors,
  parseStartPage,
} from "../metrics";
import { composedBlocks } from "../references";
import { blankAuthor } from "../storage";
import { IconTray } from "./IconTray";

export function FirstPage({
  galley,
  journal,
  openAccess,
  onChange,
  onBack,
  onNext,
}: {
  galley: Galley;
  journal: Journal;
  openAccess: IconAsset | null;
  onChange: (galley: Galley) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  const patch = (partial: Partial<Galley>) => onChange({ ...galley, ...partial, updatedAt: Date.now() });
  const start = parseStartPage(galley.startPage);
  const bodyPages = flowBody(composedBlocks(galley)).length;
  const end = start ? endPageNumber(start, bodyPages) : null;
  const numbered = numberAuthors(galley.authors);
  const citation = buildCitation({
    authors: galley.authors,
    title: galley.title,
    journal: journal.name,
    volume: galley.volume,
    issue: galley.issue,
    startPage: start,
    endPage: end,
    published: galley.published,
    doi: galley.doi,
  });
  const height = firstPageHeightInches({
    title: galley.title,
    affiliationCount: numbered.affiliations.length || 1,
    citation,
    abstract: galley.abstract,
    keywords: galley.keywords,
    topIconCount: galley.topIcons.length,
    partnerCount: galley.partnerIcons.length,
    hasIssn: Boolean(journal.issnP || journal.issnE),
  });

  return (
    <div className="desk">
      <header className="bar">
        <h1>{journal.abbreviation}</h1>
        <div className="bar-actions">
          <button type="button" className="ghost" onClick={onBack}>
            Back to journals
          </button>
          <button type="button" onClick={onNext}>
            Next: body
          </button>
        </div>
      </header>
      <div className="desk-grid">
        <form className="form-stack" onSubmit={(event) => event.preventDefault()}>
          <IconTray label="Top icons" icons={galley.topIcons} maxHeight={58} onChange={(topIcons) => patch({ topIcons })} />
          <label>
            Title
            <textarea rows={3} value={galley.title} onChange={(event) => patch({ title: event.target.value })} />
          </label>
          <fieldset>
            <legend>
              Authors
              <button
                type="button"
                className="plus"
                onClick={() => patch({ authors: [...galley.authors, blankAuthor()] })}
              >
                +
              </button>
            </legend>
            {galley.authors.map((author, index) => (
              <div key={author.id} className="author-row">
                <label>
                  Name
                  <input
                    value={author.name}
                    onChange={(event) => {
                      const authors = galley.authors.slice();
                      authors[index] = { ...author, name: event.target.value };
                      patch({ authors });
                    }}
                  />
                </label>
                <label>
                  Affiliation
                  <input
                    value={author.affiliation}
                    onChange={(event) => {
                      const authors = galley.authors.slice();
                      authors[index] = { ...author, affiliation: event.target.value };
                      patch({ authors });
                    }}
                  />
                </label>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={author.corresponding}
                    onChange={(event) => {
                      const authors = galley.authors.slice();
                      authors[index] = { ...author, corresponding: event.target.checked };
                      patch({ authors });
                    }}
                  />
                  Corresponding
                </label>
                <label>
                  Email
                  <input
                    value={author.email}
                    onChange={(event) => {
                      const authors = galley.authors.slice();
                      authors[index] = { ...author, email: event.target.value };
                      patch({ authors });
                    }}
                  />
                </label>
                {galley.authors.length > 1 && (
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => patch({ authors: galley.authors.filter((item) => item.id !== author.id) })}
                  >
                    Remove
                  </button>
                )}
              </div>
            ))}
          </fieldset>
          <p className="citation-line">{citation}</p>
          <div className="split">
            <label>
              Volume
              <input value={galley.volume} onChange={(event) => patch({ volume: event.target.value })} />
            </label>
            <label>
              Issue
              <input value={galley.issue} onChange={(event) => patch({ issue: event.target.value })} />
            </label>
            <label>
              Start page
              <input
                inputMode="numeric"
                value={galley.startPage}
                onChange={(event) => patch({ startPage: event.target.value })}
                required
              />
            </label>
            <label>
              DOI
              <input value={galley.doi} onChange={(event) => patch({ doi: event.target.value })} placeholder="10.xxxx/xxxxx" />
            </label>
          </div>
          <div className="split">
            <label>
              Received
              <input type="date" value={galley.received} onChange={(event) => patch({ received: event.target.value })} />
            </label>
            <label>
              Revised
              <input type="date" value={galley.revised} onChange={(event) => patch({ revised: event.target.value })} />
            </label>
            <label>
              Accepted
              <input type="date" value={galley.accepted} onChange={(event) => patch({ accepted: event.target.value })} />
            </label>
            <label>
              Published
              <input type="date" value={galley.published} onChange={(event) => patch({ published: event.target.value })} />
            </label>
          </div>
          <label>
            Abstract
            <textarea rows={8} value={galley.abstract} onChange={(event) => patch({ abstract: event.target.value })} />
          </label>
          <label>
            Keywords
            <input value={galley.keywords} onChange={(event) => patch({ keywords: event.target.value })} />
          </label>
          <IconTray
            label="Bottom icons"
            icons={galley.partnerIcons}
            maxHeight={40}
            onChange={(partnerIcons) => patch({ partnerIcons })}
          />
        </form>
        <aside className="preview-column">
          <p className="muted">
            7.5 in wide · {height.toFixed(2)} in tall
          </p>
          <FrontSheet galley={galley} journal={journal} openAccess={openAccess} />
        </aside>
      </div>
    </div>
  );
}

export function FrontSheet({
  galley,
  journal,
  openAccess,
}: {
  galley: Galley;
  journal: Journal;
  openAccess: IconAsset | null;
}) {
  const start = parseStartPage(galley.startPage);
  const end = start ? endPageNumber(start, flowBody(composedBlocks(galley)).length) : null;
  const numbered = numberAuthors(galley.authors);
  const citation = buildCitation({
    authors: galley.authors,
    title: galley.title,
    journal: journal.name,
    volume: galley.volume,
    issue: galley.issue,
    startPage: start,
    endPage: end,
    published: galley.published,
    doi: galley.doi,
  });
  const height = firstPageHeightInches({
    title: galley.title,
    affiliationCount: numbered.affiliations.length || 1,
    citation,
    abstract: galley.abstract,
    keywords: galley.keywords,
    topIconCount: galley.topIcons.length,
    partnerCount: galley.partnerIcons.length,
    hasIssn: Boolean(journal.issnP || journal.issnE),
  });
  return (
    <div className="sheet-frame" style={{ height: `${height / 2}in` }}>
      <article className="sheet front" style={{ minHeight: `${height}in` }}>
        <SheetHeader journal={journal} openAccess={openAccess} />
        <div className="logo-line">
          {galley.topIcons.map((icon) => (
            <img key={icon.id} src={icon.dataUrl} alt={icon.name} />
          ))}
        </div>
        {(journal.issnP || journal.issnE) && (
          <p className="issn">
            {journal.issnP && <span>ISSN-P {journal.issnP}</span>}
            {journal.issnE && <span>ISSN-E {journal.issnE}</span>}
          </p>
        )}
        <h2>{galley.title.trim() || "Title"}</h2>
        <p className="authors">
          {numbered.authors.map((author, index) => (
            <span key={author.id}>
              {index > 0 ? ", " : ""}
              {author.name || "Author"}
              <sup>
                {author.affiliationNo}
                {author.corresponding ? "*" : ""}
              </sup>
            </span>
          ))}
        </p>
        {numbered.affiliations.map((affiliation, index) => (
          <p key={`${affiliation}-${index}`} className="affiliation">
            <sup>{index + 1}</sup>
            {affiliation}
          </p>
        ))}
        {numbered.authors.some((author) => author.corresponding && author.email) && (
          <p className="affiliation">
            <strong>*Correspondence: </strong>
            {numbered.authors
              .filter((author) => author.corresponding && author.email)
              .map((author) => author.email)
              .join("; ")}
          </p>
        )}
        <p>{citation}</p>
        <p className="dates">{dateLine(galley)}</p>
        <p className="abstract">
          <span className="drop">{galley.abstract.trim().charAt(0) || "A"}</span>
          {galley.abstract.trim().slice(1) || "bstract"}
        </p>
        <p>
          <strong>Keywords: </strong>
          {galley.keywords}
        </p>
        <div className="partner-grid">
          {galley.partnerIcons.map((icon) => (
            <img key={icon.id} src={icon.dataUrl} alt={icon.name} />
          ))}
        </div>
        <SheetFooter galley={galley} page={start ?? "—"} />
      </article>
    </div>
  );
}

export function SheetHeader({ journal, openAccess }: { journal: Journal; openAccess: IconAsset | null }) {
  return (
    <header className="sheet-header">
      {openAccess && <img src={openAccess.dataUrl} alt="Open Access" />}
      <strong>OPEN ACCESS</strong>
      <span>{journal.name}</span>
    </header>
  );
}

export function SheetFooter({ galley, page }: { galley: Galley; page: number | string }) {
  const month = galley.published
    ? new Date(`${galley.published}T00:00:00`).toLocaleString("en-US", { month: "long", year: "numeric" })
    : "Month Year";
  return (
    <footer className="sheet-footer">
      <span>
        {month} | Vol {galley.volume || "00"} | Issue {galley.issue || "00"}
      </span>
      <span className="footer-pages">Page | {page}</span>
    </footer>
  );
}
