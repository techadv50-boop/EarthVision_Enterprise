import type { BodyBlock, Galley, ReferenceItem, ReferenceKind, ReferenceStyleId } from "./types";
import { newId } from "./metrics";

export const REFERENCE_STYLES: { id: ReferenceStyleId; label: string }[] = [
  { id: "ieee", label: "IEEE" },
  { id: "apa", label: "APA" },
  { id: "chicago", label: "Chicago" },
  { id: "vancouver", label: "Vancouver" },
  { id: "harvard", label: "Harvard" },
  { id: "mla", label: "MLA" },
];

export type ParsedAuthor = { family: string; given: string };

export function emptyReference(): ReferenceItem {
  return {
    id: newId(),
    kind: "journal",
    raw: "",
    authors: "",
    title: "",
    container: "",
    volume: "",
    issue: "",
    pages: "",
    year: "",
    doi: "",
    publisher: "",
    city: "",
  };
}

function looksLikeInitials(token: string): boolean {
  return /^(?:[A-Z]\.-?)+$/.test(token) || /^[A-Z]\.?$/.test(token);
}

function parseSingle(token: string): ParsedAuthor {
  const clean = token.trim().replace(/\.$/, "");
  if (!clean) return { family: "", given: "" };
  if (clean.includes(",")) {
    const [family, given] = clean.split(",").map((part) => part.trim());
    return { family, given: given || "" };
  }
  const parts = clean.split(/\s+/);
  if (parts.length === 1) return { family: parts[0], given: "" };
  return { family: parts[parts.length - 1], given: parts.slice(0, -1).join(" ") };
}

export function parseAuthorList(raw: string): ParsedAuthor[] {
  const cleaned = raw.replace(/\s+and\s+/gi, ", ").replace(/[.,\s]+$/, "");
  const tokens = cleaned.split(",").map((token) => token.trim()).filter(Boolean);
  const authors: ParsedAuthor[] = [];
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    const next = tokens[index + 1];
    if (next && looksLikeInitials(next) && !token.includes(" ") && !looksLikeInitials(token)) {
      authors.push({ family: token, given: next });
      index += 1;
      continue;
    }
    const author = parseSingle(token);
    if (author.family) authors.push(author);
  }
  return authors;
}

function initials(given: string): string {
  return given
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part.replace(/\./g, "").charAt(0).toUpperCase())
    .filter(Boolean)
    .map((letter) => `${letter}.`)
    .join(" ");
}

function ieeeAuthors(authors: ParsedAuthor[]): string {
  const names = authors.map((author) => {
    const given = initials(author.given);
    return given ? `${given} ${author.family}` : author.family;
  });
  if (names.length <= 1) return names[0] || "";
  return `${names.slice(0, -1).join(", ")}, and ${names[names.length - 1]}`;
}

function apaAuthors(authors: ParsedAuthor[]): string {
  const names = authors.map((author) => {
    const given = initials(author.given);
    return given ? `${author.family}, ${given}` : author.family;
  });
  if (names.length <= 1) return names[0] || "";
  if (names.length === 2) return `${names[0]}, & ${names[1]}`;
  return `${names.slice(0, -1).join(", ")}, & ${names[names.length - 1]}`;
}

function chicagoAuthors(authors: ParsedAuthor[]): string {
  const names = authors.map((author, index) => {
    const given = initials(author.given);
    if (index === 0) return given ? `${author.family}, ${given}` : author.family;
    return given ? `${given} ${author.family}` : author.family;
  });
  if (names.length <= 1) return names[0] || "";
  return `${names.slice(0, -1).join(", ")}, and ${names[names.length - 1]}`;
}

function vancouverAuthors(authors: ParsedAuthor[]): string {
  return authors
    .map((author) => {
      const given = initials(author.given).replace(/\.\s*/g, "").replace(/\.$/, "");
      return given ? `${author.family} ${given}` : author.family;
    })
    .join(", ");
}

function mlaAuthors(authors: ParsedAuthor[]): string {
  if (authors.length === 0) return "";
  const first = authors[0];
  const firstGiven = initials(first.given);
  const head = firstGiven ? `${first.family}, ${firstGiven}` : first.family;
  if (authors.length === 1) return head;
  const rest = authors.slice(1).map((author) => {
    const given = initials(author.given);
    return given ? `${given} ${author.family}` : author.family;
  });
  return `${head}, and ${rest.join(", ")}`;
}

function harvardAuthors(authors: ParsedAuthor[]): string {
  const names = authors.map((author) => {
    const given = initials(author.given);
    return given ? `${author.family}, ${given}` : author.family;
  });
  if (names.length <= 1) return names[0] || "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

function pagesDash(pages: string): string {
  return pages.replace(/\s+/g, "").replace("-", "–");
}

function doiLink(doi: string): string {
  return doi.replace(/^https?:\/\/(dx\.)?doi\.org\//i, "");
}

function detectKind(text: string): ReferenceKind {
  if (/proceedings|conference|symposium|workshop/i.test(text)) return "conference";
  if (/\b(press|publisher|publishing)\b/i.test(text)) return "book";
  return "journal";
}

export function parseReference(raw: string): ReferenceItem {
  const item = emptyReference();
  item.raw = raw.trim();
  let text = raw.replace(/^\s*\[\d+\]\s*/, "").trim();
  const doiMatch = text.match(/10\.\d{4,9}\/[^\s,;]+/i);
  if (doiMatch) {
    item.doi = doiMatch[0].replace(/[.)]+$/, "");
    text = text.replace(doiMatch[0], " ");
  }
  text = text.replace(/\bdoi:\s*/i, " ").replace(/\s+/g, " ").trim();
  const yearMatch = text.match(/\b(19|20)\d{2}\b/);
  if (yearMatch) item.year = yearMatch[0];
  const pagesMatch = text.match(/\bpp?\.?\s*(\d+\s*[-–]\s*\d+)/i) || text.match(/:\s*(\d+\s*[-–]\s*\d+)/);
  if (pagesMatch) item.pages = pagesMatch[1].replace(/\s/g, "");
  const volIssue = text.match(/\b(\d+)\s*\((\d+)\)/);
  const vol = text.match(/\bvol(?:ume)?\.?\s*(\d+)/i);
  const issue = text.match(/\b(?:no|issue)\.?\s*(\d+)/i);
  if (vol) item.volume = vol[1];
  if (issue) item.issue = issue[1];
  if (!item.volume && volIssue) {
    item.volume = volIssue[1];
    item.issue = volIssue[2];
  }
  const quoted = text.match(/[“"]([^”"]+)[”"]/);
  if (quoted) {
    item.title = quoted[1].trim().replace(/[,.\s]+$/, "");
    item.authors = text.slice(0, quoted.index).replace(/[,\s]+$/, "");
    let after = text.slice((quoted.index || 0) + quoted[0].length);
    after = after.replace(/^[,.\s]+/, "");
    after = after.split(/\b(?:vol(?:ume)?|no|issue|pp|doi)\b/i)[0];
    after = after.replace(/\b(19|20)\d{2}\b.*/, "").replace(/[,\s]+$/, "");
    item.container = after.trim();
  } else {
    const bits = text.split(/\.\s+/);
    if (bits.length >= 2) {
      item.authors = bits[0];
      item.title = bits[1].replace(/[“"]/g, "");
      item.container = bits.slice(2).join(". ").split(/\b(?:vol(?:ume)?|pp)\b/i)[0].replace(/[,\s]+$/, "");
    } else {
      item.title = text;
    }
  }
  const probe = `${item.container} ${text}`;
  item.kind = detectKind(probe);
  if (item.kind !== "journal") {
    const press = probe.match(/([A-Z][^,]{2,40}(?:Press|Publisher|Publishing))/);
    if (press) item.publisher = press[1].trim();
  }
  return item;
}

function authorsOf(item: ReferenceItem): ParsedAuthor[] {
  return parseAuthorList(item.authors);
}

export function formatReference(item: ReferenceItem, style: ReferenceStyleId, index: number): string {
  const authors = authorsOf(item);
  const doi = doiLink(item.doi);
  const pages = pagesDash(item.pages);
  const title = item.title.trim();
  const container = item.container.trim();
  const year = item.year.trim();

  if (style === "ieee") {
    const who = ieeeAuthors(authors);
    if (item.kind === "book") {
      const place = [item.city, item.publisher].filter(Boolean).join(": ");
      return `[${index}] ${[who, title && `${title}.`, place, year].filter(Boolean).join(", ")}${doi ? `, doi: ${doi}` : ""}.`.replace(".,", ".");
    }
    if (item.kind === "conference") {
      return `[${index}] ${who}, “${title},” in ${container}${year ? `, ${year}` : ""}${pages ? `, pp. ${pages}` : ""}${doi ? `, doi: ${doi}` : ""}.`;
    }
    const vol = item.volume ? `vol. ${item.volume}` : "";
    const no = item.issue ? `no. ${item.issue}` : "";
    const tail = [vol, no, pages ? `pp. ${pages}` : "", year, doi ? `doi: ${doi}` : ""].filter(Boolean).join(", ");
    return `[${index}] ${who}, “${title},” ${container}${tail ? `, ${tail}` : ""}.`;
  }

  if (style === "apa") {
    const who = apaAuthors(authors);
    if (item.kind === "book") {
      return `${who} (${year}). ${title}. ${[item.publisher, doi && `https://doi.org/${doi}`].filter(Boolean).join(". ")}`.trim();
    }
    if (item.kind === "conference") {
      return `${who} (${year}). ${title}. ${container}${pages ? ` (pp. ${pages})` : ""}.${doi ? ` https://doi.org/${doi}` : ""}`;
    }
    const loc = [item.volume && item.issue ? `${item.volume}(${item.issue})` : item.volume, pages].filter(Boolean).join(", ");
    return `${who} (${year}). ${title}. ${container}${loc ? `, ${loc}` : ""}.${doi ? ` https://doi.org/${doi}` : ""}`;
  }

  if (style === "chicago") {
    const who = chicagoAuthors(authors);
    if (item.kind === "book") {
      return `${who}. ${year}. ${title}. ${[item.city, item.publisher].filter(Boolean).join(": ")}.`;
    }
    const loc = [item.volume, item.issue ? `(${item.issue})` : "", pages ? `: ${pages}` : ""].join(" ").replace(/\s+/g, " ").trim();
    return `${who}. ${year}. “${title}.” ${container}${loc ? ` ${loc}` : ""}.${doi ? ` https://doi.org/${doi}.` : ""}`;
  }

  if (style === "vancouver") {
    const who = vancouverAuthors(authors);
    if (item.kind === "book") {
      return `${index}. ${who}. ${title}. ${[item.city, item.publisher].filter(Boolean).join(": ")}; ${year}.`;
    }
    const loc = `${year}${item.volume ? `;${item.volume}` : ""}${item.issue ? `(${item.issue})` : ""}${pages ? `:${pages}` : ""}`;
    return `${index}. ${who}. ${title}. ${container}. ${loc}.${doi ? ` doi: ${doi}.` : ""}`;
  }

  if (style === "harvard") {
    const who = harvardAuthors(authors);
    if (item.kind === "book") {
      return `${who} (${year}) ${title}. ${[item.city, item.publisher].filter(Boolean).join(": ")}.`;
    }
    const loc = [item.volume && item.issue ? `${item.volume}(${item.issue})` : item.volume, pages ? `pp. ${pages}` : ""].filter(Boolean).join(", ");
    return `${who} (${year}) '${title}', ${container}${loc ? `, ${loc}` : ""}.${doi ? ` doi: ${doi}.` : ""}`;
  }

  const who = mlaAuthors(authors);
  if (item.kind === "book") {
    return `${who}. ${title}. ${[item.publisher, year].filter(Boolean).join(", ")}.`;
  }
  const loc = [item.volume ? `vol. ${item.volume}` : "", item.issue ? `no. ${item.issue}` : "", year, pages ? `pp. ${pages}` : ""].filter(Boolean).join(", ");
  return `${who}. “${title}.” ${container}${loc ? `, ${loc}` : ""}.${doi ? ` doi:${doi}.` : ""}`;
}

export function formattedReferences(galley: Pick<Galley, "references" | "referenceStyle">): string[] {
  return galley.references
    .filter((item) => item.title || item.authors || item.raw)
    .map((item, index) => formatReference(item, galley.referenceStyle, index + 1).replace(/\s+/g, " ").replace(" .", ".").trim());
}

export function composedBlocks(galley: Galley): BodyBlock[] {
  const lines = formattedReferences(galley);
  if (lines.length === 0) return galley.blocks;
  return [
    ...galley.blocks,
    { id: "references-heading", type: "heading", text: "References:" },
    ...lines.map((text, index) => ({ id: `reference-line-${index}`, type: "referenceLine" as const, text })),
  ];
}
