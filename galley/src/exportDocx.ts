import {
  AlignmentType,
  BorderStyle,
  Document,
  Footer,
  Header,
  ImageRun,
  PageNumber,
  PageOrientation,
  Paragraph,
  Table,
  TableCell,
  TableRow,
  TabStopType,
  TextRun,
  VerticalAlign,
  WidthType,
  convertInchesToTwip,
  type FileChild,
  type ISectionOptions,
} from "docx";
import type { BodyBlock, Galley, IconAsset, Journal } from "./types";
import {
  PAGE,
  buildCitation,
  dateLine,
  endPageNumber,
  figureNumber,
  firstPageHeightInches,
  flowBody,
  formatMonthYear,
  numberAuthors,
  parseStartPage,
  tableNumber,
} from "./metrics";
import { composedBlocks } from "./references";

const FONT = "Garamond";
const NONE = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const NO_BORDERS = { top: NONE, bottom: NONE, left: NONE, right: NONE, insideHorizontal: NONE, insideVertical: NONE };
const GRID = { style: BorderStyle.SINGLE, size: 4, color: "444444" };
const GRID_BORDERS = { top: GRID, bottom: GRID, left: GRID, right: GRID };

function imageBytes(dataUrl: string): { data: Uint8Array; type: "png" | "jpg" | "gif" | "bmp" } | null {
  const match = /^data:image\/(png|jpeg|jpg|gif|bmp);base64,(.+)$/i.exec(dataUrl);
  if (!match) return null;
  const raw = atob(match[2]);
  const data = new Uint8Array(raw.length);
  for (let index = 0; index < raw.length; index += 1) data[index] = raw.charCodeAt(index);
  const kind = match[1].toLowerCase();
  const type = kind === "png" ? "png" : kind === "gif" ? "gif" : kind === "bmp" ? "bmp" : "jpg";
  return { data, type };
}

function picture(icon: IconAsset, maxHeight: number): ImageRun | null {
  const parsed = imageBytes(icon.dataUrl);
  if (!parsed) return null;
  const height = Math.min(maxHeight, icon.heightPx || maxHeight);
  const width = Math.max(12, Math.round(((icon.widthPx || height) / (icon.heightPx || height)) * height));
  return new ImageRun({
    type: parsed.type,
    data: parsed.data,
    transformation: { width, height },
  });
}

function run(text: string, options: { bold?: boolean; italics?: boolean; size?: number; super?: boolean; sub?: boolean } = {}): TextRun {
  return new TextRun({
    text,
    font: FONT,
    bold: options.bold,
    italics: options.italics,
    size: options.size ?? 24,
    superScript: options.super,
    subScript: options.sub,
  });
}

function bodyParagraph(children: TextRun[], extras: { center?: boolean; indent?: boolean; after?: number } = {}): Paragraph {
  return new Paragraph({
    alignment: extras.center ? AlignmentType.CENTER : AlignmentType.BOTH,
    spacing: { before: 0, after: extras.after ?? 0, line: 240, lineRule: "auto" },
    indent: extras.indent ? { firstLine: convertInchesToTwip(0.5) } : undefined,
    children,
  });
}

function headerFor(journalName: string, openAccess: IconAsset | null, widthIn: number): Header {
  const mark = openAccess ? picture(openAccess, 28) : null;
  return new Header({
    children: [
      new Paragraph({
        tabStops: [{ type: TabStopType.RIGHT, position: convertInchesToTwip(widthIn) }],
        spacing: { before: 0, after: 60 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "222222", space: 1 } },
        children: [
          ...(mark ? [mark, run("  ")] : []),
          run("OPEN ACCESS", { bold: true, size: 16 }),
          run("\t"),
          run(journalName, { size: 20 }),
        ],
      }),
    ],
  });
}

function footerFor(monthLine: string, widthIn: number): Footer {
  return new Footer({
    children: [
      new Paragraph({
        tabStops: [{ type: TabStopType.RIGHT, position: convertInchesToTwip(widthIn) }],
        border: { top: { style: BorderStyle.SINGLE, size: 6, color: "222222", space: 1 } },
        spacing: { before: 60, after: 0 },
        children: [
          run(monthLine, { size: 20 }),
          run("\t"),
          run("Page | ", { size: 20 }),
          new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 20 }),
        ],
      }),
    ],
  });
}

function iconRow(icons: IconAsset[], columns: number, cellWidthIn: number, maxHeight: number): Table {
  const rows: IconAsset[][] = [];
  for (let index = 0; index < icons.length; index += columns) rows.push(icons.slice(index, index + columns));
  return new Table({
    width: { size: convertInchesToTwip(cellWidthIn * columns), type: WidthType.DXA },
    borders: NO_BORDERS,
    rows: rows.map(
      (row) =>
        new TableRow({
          cantSplit: true,
          children: Array.from({ length: columns }, (_, column) => {
            const icon = row[column];
            const image = icon ? picture(icon, maxHeight) : null;
            return new TableCell({
              width: { size: convertInchesToTwip(cellWidthIn), type: WidthType.DXA },
              borders: NO_BORDERS,
              verticalAlign: VerticalAlign.CENTER,
              margins: { top: 40, bottom: 40, left: 40, right: 40 },
              children: [
                new Paragraph({
                  alignment: AlignmentType.CENTER,
                  children: image ? [image] : [run("")],
                }),
              ],
            });
          }),
        }),
    ),
  });
}

function dataTable(rows: string[][]): Table {
  const columns = Math.max(...rows.map((row) => row.length), 1);
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    rows: rows.map(
      (row, rowIndex) =>
        new TableRow({
          cantSplit: true,
          tableHeader: rowIndex === 0,
          children: Array.from({ length: columns }, (_, column) => {
            return new TableCell({
              borders: GRID_BORDERS,
              width: { size: Math.floor(100 / columns), type: WidthType.PERCENTAGE },
              margins: { top: 40, bottom: 40, left: 60, right: 60 },
              children: [
                new Paragraph({
                  spacing: { before: 0, after: 0 },
                  children: [run(row[column] ?? "", { bold: rowIndex === 0, size: 20 })],
                }),
              ],
            });
          }),
        }),
    ),
  });
}

function frontMatter(galley: Galley, journal: Journal, citation: string): FileChild[] {
  const { authors, affiliations } = numberAuthors(galley.authors);
  const children: FileChild[] = [];
  const contentWidth = PAGE.widthIn - PAGE.marginLeftIn - PAGE.marginRightIn;
  if (galley.topIcons.length) children.push(iconRow(galley.topIcons, Math.min(galley.topIcons.length, 4), contentWidth / Math.min(galley.topIcons.length, 4), 58));
  const issn = [journal.issnP && `ISSN-P ${journal.issnP}`, journal.issnE && `ISSN-E ${journal.issnE}`].filter(Boolean).join("    ");
  if (issn) children.push(bodyParagraph([run(issn, { size: 18 })], { center: true, after: 80 }));
  children.push(
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 120, after: 120, line: 276, lineRule: "auto" },
      children: [run(galley.title.trim() || "Untitled", { bold: true, size: 32 })],
    }),
  );
  const nameRuns: TextRun[] = [];
  authors.forEach((author, index) => {
    if (index > 0) nameRuns.push(run(", "));
    nameRuns.push(run(author.name.trim()));
    nameRuns.push(run(String(author.affiliationNo), { super: true }));
    if (author.corresponding) nameRuns.push(run("*", { super: true, bold: true }));
  });
  if (nameRuns.length) children.push(bodyParagraph(nameRuns, { after: 40 }));
  affiliations.forEach((affiliation, index) => {
    children.push(bodyParagraph([run(`${index + 1}`, { super: true }), run(affiliation)], { after: 0 }));
  });
  const emails = authors.filter((author) => author.corresponding && author.email.trim()).map((author) => author.email.trim());
  if (emails.length) {
    children.push(bodyParagraph([run("*Correspondence: ", { bold: true }), run(emails.join("; "))], { after: 80 }));
  }
  children.push(bodyParagraph([run("Citation", { bold: true }), run(` | ${citation.replace(/^Citation \| /, "")}`)], { after: 40 }));
  const dates = dateLine(galley);
  children.push(
    bodyParagraph(
      [
        run("Received", { bold: true }),
        run(` | ${dates.split("  ")[0]?.replace(/^Received \| /, "") || "—"}  `),
        run("Revised", { bold: true }),
        run(` | ${dates.split("  ")[1]?.replace(/^Revised \| /, "") || "—"}  `),
        run("Accepted", { bold: true }),
        run(` | ${dates.split("  ")[2]?.replace(/^Accepted \| /, "") || "—"}  `),
        run("Published", { bold: true }),
        run(` | ${dates.split("  ")[3]?.replace(/^Published \| /, "") || "—"}`),
      ],
      { after: 80 },
    ),
  );
  const abstract = galley.abstract.trim();
  const letter = abstract.charAt(0) || " ";
  const rest = abstract.slice(1);
  children.push(
    new Table({
      width: { size: convertInchesToTwip(contentWidth), type: WidthType.DXA },
      borders: NO_BORDERS,
      rows: [
        new TableRow({
          cantSplit: true,
          children: [
            new TableCell({
              width: { size: convertInchesToTwip(0.48), type: WidthType.DXA },
              borders: NO_BORDERS,
              verticalAlign: VerticalAlign.TOP,
              children: [
                new Paragraph({
                  children: [run(letter, { bold: true, size: 72 })],
                }),
              ],
            }),
            new TableCell({
              borders: NO_BORDERS,
              verticalAlign: VerticalAlign.CENTER,
              children: [bodyParagraph([run(rest)])],
            }),
          ],
        }),
      ],
    }),
  );
  children.push(
    bodyParagraph([run("Keywords: ", { bold: true }), run(galley.keywords.trim())], { after: 120 }),
  );
  if (galley.partnerIcons.length) children.push(iconRow(galley.partnerIcons, 5, contentWidth / 5, 40));
  return children;
}

function blockChildren(block: BodyBlock, galley: Galley): FileChild[] {
  switch (block.type) {
    case "heading":
      return [bodyParagraph([run(block.text.trim().endsWith(":") ? block.text.trim() : `${block.text.trim()}:`, { bold: true })], { after: 60 })];
    case "section": {
      const heading = block.heading.trim();
      const titled = heading ? (heading.endsWith(":") ? heading : `${heading}:`) : "";
      return [
        ...(titled ? [bodyParagraph([run(titled, { bold: true })], { after: 60 })] : []),
        ...(block.text.trim() ? [bodyParagraph([run(block.text)], { indent: true })] : []),
      ];
    }
    case "paragraph":
      return [bodyParagraph([run(block.text)], { indent: true })];
    case "referenceLine":
      return [bodyParagraph([run(block.text)], { after: 60 })];
    case "figure": {
      const image = block.dataUrl
        ? picture(
            { id: block.id, name: "figure", dataUrl: block.dataUrl, widthPx: block.widthPx || 480, heightPx: block.heightPx || 280 },
            220,
          )
        : null;
      const number = figureNumber(galley.blocks, block.id);
      return [
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { before: 120, after: 40 },
          children: image ? [image] : [run("")],
        }),
        bodyParagraph([run(`Figure ${number}. `, { bold: true }), run(block.caption.trim())], { center: true, after: 120 }),
      ];
    }
    case "table": {
      const number = tableNumber(galley.blocks, block.id);
      return [
        bodyParagraph([run(`Table ${number}. `, { bold: true }), run(block.caption.trim())], { center: true, after: 60 }),
        dataTable(block.rows.length ? block.rows : [[" "]]),
        bodyParagraph([run("")], { after: 80 }),
      ];
    }
    case "equation": {
      const children: FileChild[] = [];
      let runs: TextRun[] = [];
      const flush = () => {
        if (!runs.length) return;
        children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 40, after: 40 }, children: runs }));
        runs = [];
      };
      for (const atom of block.atoms || []) {
        if (atom.kind === "frac") {
          flush();
          children.push(
            new Table({
              width: { size: convertInchesToTwip(1.1), type: WidthType.DXA },
              alignment: AlignmentType.CENTER,
              borders: NO_BORDERS,
              rows: [
                new TableRow({
                  cantSplit: true,
                  children: [
                    new TableCell({
                      borders: { ...NO_BORDERS, bottom: { style: BorderStyle.SINGLE, size: 8, color: "000000" } },
                      children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [run(atom.num)] })],
                    }),
                  ],
                }),
                new TableRow({
                  cantSplit: true,
                  children: [
                    new TableCell({
                      borders: NO_BORDERS,
                      children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [run(atom.den)] })],
                    }),
                  ],
                }),
              ],
            }),
          );
        } else if (atom.kind === "sup") runs.push(run(atom.value, { super: true }));
        else if (atom.kind === "sub") runs.push(run(atom.value, { sub: true }));
        else runs.push(run(atom.value));
      }
      flush();
      if (block.number) children.push(bodyParagraph([run(`(${block.number})`)], { center: true, after: 80 }));
      return children.length ? children : [bodyParagraph([run("")])];
    }
    case "pageBreak":
      return [];
  }
}

function pageProperties(widthIn: number, heightIn: number, landscape: boolean, start: number | null) {
  return {
    page: {
      size: {
        width: convertInchesToTwip(widthIn),
        height: convertInchesToTwip(heightIn),
        orientation: landscape ? PageOrientation.LANDSCAPE : PageOrientation.PORTRAIT,
      },
      margin: {
        top: convertInchesToTwip(PAGE.marginTopIn),
        right: convertInchesToTwip(PAGE.marginRightIn),
        bottom: convertInchesToTwip(PAGE.marginBottomIn),
        left: convertInchesToTwip(PAGE.marginLeftIn),
        header: convertInchesToTwip(0.05),
        footer: convertInchesToTwip(0.2),
      },
      pageNumbers: start ? { start } : undefined,
    },
  };
}

export function galleyDocument(galley: Galley, journal: Journal, openAccess: IconAsset | null): Document {
  const start = parseStartPage(galley.startPage) ?? 1;
  const manuscript = composedBlocks(galley);
  const bodyPages = flowBody(manuscript);
  const end = endPageNumber(start, bodyPages.length);
  const citation = buildCitation({
    authors: galley.authors,
    title: galley.title,
    abbreviation: journal.abbreviation,
    volume: galley.volume,
    issue: galley.issue,
    startPage: start,
    endPage: end,
    published: galley.published,
  });
  const height = firstPageHeightInches({
    title: galley.title,
    affiliationCount: numberAuthors(galley.authors).affiliations.length || 1,
    citation,
    abstract: galley.abstract,
    keywords: galley.keywords,
    topIconCount: galley.topIcons.length,
    partnerCount: galley.partnerIcons.length,
    hasIssn: Boolean(journal.issnP || journal.issnE),
  });
  const month = formatMonthYear(galley.published);
  const monthLine = `${month || "Month Year"} | Vol ${galley.volume.trim() || "00"} | Issue ${galley.issue.trim() || "00"}`;
  const portraitWidth = PAGE.widthIn - PAGE.marginLeftIn - PAGE.marginRightIn;
  const landscapeWidth = PAGE.bodyHeightIn - PAGE.marginLeftIn - PAGE.marginRightIn;

  const sections: ISectionOptions[] = [
    {
      properties: pageProperties(PAGE.widthIn, height, false, start),
      headers: { default: headerFor(journal.name, openAccess, portraitWidth) },
      footers: { default: footerFor(monthLine, portraitWidth) },
      children: frontMatter(galley, journal, citation),
    },
  ];

  let bucket: FileChild[] = [];
  const pushPortrait = () => {
    if (bucket.length === 0) return;
    sections.push({
      properties: pageProperties(PAGE.widthIn, PAGE.bodyHeightIn, false, null),
      headers: { default: headerFor(journal.name, openAccess, portraitWidth) },
      footers: { default: footerFor(monthLine, portraitWidth) },
      children: bucket,
    });
    bucket = [];
  };

  for (const block of manuscript) {
    if (block.type === "pageBreak") {
      bucket.push(new Paragraph({ children: [], pageBreakBefore: true }));
      continue;
    }
    if (block.type === "table" && block.landscape) {
      pushPortrait();
      sections.push({
        properties: pageProperties(PAGE.bodyHeightIn, PAGE.widthIn, true, null),
        headers: { default: headerFor(journal.name, openAccess, landscapeWidth) },
        footers: { default: footerFor(monthLine, landscapeWidth) },
        children: blockChildren(block, galley),
      });
      continue;
    }
    bucket.push(...blockChildren(block, galley));
  }
  pushPortrait();
  if (sections.length === 1) {
    sections.push({
      properties: pageProperties(PAGE.widthIn, PAGE.bodyHeightIn, false, null),
      headers: { default: headerFor(journal.name, openAccess, portraitWidth) },
      footers: { default: footerFor(monthLine, portraitWidth) },
      children: [bodyParagraph([run("")])],
    });
  }

  return new Document({ sections });
}

export function suggestedFileName(journal: Journal, galley: Galley): string {
  const { authors } = numberAuthors(galley.authors);
  const surname = authors[0] ? authorSurname(authors[0].name) : "Author";
  const title = (galley.title.trim() || "Untitled").replace(/[^\w]+/g, "_").replace(/^_|_$/g, "").slice(0, 40);
  const abbr = journal.abbreviation.trim() || "Journal";
  return `${abbr}_${surname}_${title}_galley.docx`;
}

function authorSurname(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "Author";
  const surname = parts[parts.length - 1];
  return surname.charAt(0).toUpperCase() + surname.slice(1);
}
