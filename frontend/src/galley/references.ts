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
    month: "",
    url: "",
    publisher: "",
    city: "",
    extra: "",
  };
}

export function splitReferenceBlob(raw: string): string[] {
  const trimmed = raw.replace(/\r\n/g, "\n").trim();
  if (!trimmed) return [];
  const blocks = trimmed
    .split(/\n\s*\n/)
    .map((part) => part.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  if (blocks.length > 1) return blocks;
  const lines = trimmed
    .split(/\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length > 1 && lines.filter((line) => /^(\[\d+\]|\d+[\.)])\s*/.test(line)).length >= 2) return lines;
  return blocks;
}

export function segregateReferences(raw: string): ReferenceItem[] {
  const items: ReferenceItem[] = [];
  for (const blob of splitReferenceBlob(raw)) {
    items.push(parseReference(blob));
  }
  return items;
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
  if (/\bin\s+proceedings\b|\bconference\b|\bsymposium\b|\bworkshop\b/i.test(text)) return "conference";
  if (/\b(press|publisher|publishing)\b/i.test(text) && !/\bvol(?:ume)?\.?\s*\d+/i.test(text)) return "book";
  return "journal";
}

function leftoverOf(original: string, item: ReferenceItem): string {
  let rest = original.replace(/^\s*(?:\[\d+\]|\d+[.)])\s*/, "");
  const pieces = [
    item.authors,
    item.title,
    item.container,
    item.publisher,
    item.city,
    item.volume ? `vol. ${item.volume}` : "",
    item.volume ? `volume ${item.volume}` : "",
    item.volume,
    item.issue ? `no. ${item.issue}` : "",
    item.issue ? `issue ${item.issue}` : "",
    item.issue,
    item.pages ? `pp. ${item.pages}` : "",
    item.pages ? `pp ${item.pages}` : "",
    item.pages,
    item.year,
    item.month,
    item.doi,
    item.url,
  ].filter(Boolean);
  for (const piece of pieces) {
    const escaped = piece.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    rest = rest.replace(new RegExp(escaped, "i"), " ");
  }
  rest = rest.replace(/\b(doi:|https?:\/\/(?:dx\.)?doi\.org\/|vol(?:ume)?\.?|iss(?:ue)?\.?|pp\.?)\b/gi, " ");
  rest = rest.replace(/[“”"'[\]()]/g, " ").replace(/[.,;:/]+/g, " ").replace(/\s+/g, " ").trim();
  return rest;
}

export function parseReference(raw: string): ReferenceItem {
  const item = emptyReference();
  item.raw = raw.trim();
  let text = raw.replace(/^\s*(?:\[\d+\]|\d+[.)])\s*/, "").trim();
  const doiMatch = text.match(/(?:doi:\s*)?(?:https?:\/\/(?:dx\.)?doi\.org\/)?(10\.\d{4,9}\/[^\s,;]+)/i);
  if (doiMatch) {
    item.doi = doiMatch[1].replace(/[.)]+$/, "");
    text = text.replace(doiMatch[0], " ");
  }
  const urlMatch = text.match(/https?:\/\/[^\s,;]+/i);
  if (urlMatch && !/doi\.org/i.test(urlMatch[0])) {
    item.url = urlMatch[0].replace(/[.)]+$/, "");
    text = text.replace(urlMatch[0], " ");
  }
  const monthMatch = text.match(
    /\b(January|February|March|April|May|June|July|August|September|October|November|December)\b/i,
  );
  if (monthMatch) {
    item.month = monthMatch[1].charAt(0).toUpperCase() + monthMatch[1].slice(1).toLowerCase();
    text = text.replace(monthMatch[0], " ");
  }
  text = text.replace(/\bdoi:\s*/i, " ").replace(/\s+/g, " ").trim();
  const yearMatch = text.match(/\b(19|20)\d{2}\b/);
  if (yearMatch) item.year = yearMatch[0];
  const pagesMatch = text.match(/\bpp?\.?\s*(\d+\s*[-–]\s*\d+|\d+)/i) || text.match(/:\s*(\d+\s*[-–]\s*\d+)/);
  if (pagesMatch) item.pages = pagesMatch[1].replace(/\s/g, "");
  const volIssue = text.match(/\b(\d+)\s*\((\d+)\)/);
  const vol = text.match(/\bvol(?:ume)?\.?\s*(\d+)/i);
  const issueAfterVol = text.match(/\bvol(?:ume)?\.?\s*\d+\s*,\s*(?:no|iss(?:ue)?)\.?\s*(\d+)/i);
  const issueWord = text.match(/\bissue\.?\s*(\d+)/i);
  if (vol) item.volume = vol[1];
  if (issueAfterVol) item.issue = issueAfterVol[1];
  else if (issueWord) item.issue = issueWord[1];
  if (!item.volume && volIssue) {
    item.volume = volIssue[1];
    item.issue = volIssue[2];
  }
  const quoted = text.match(/[“"]([^”"]+)[”"]/);
  if (quoted) {
    item.title = quoted[1].trim().replace(/[,.\s]+$/, "");
    item.authors = text.slice(0, quoted.index).replace(/[,\s]+$/, "");
    let after = text.slice((quoted.index || 0) + quoted[0].length);
    after = after.replace(/^[,.\s]+/, "").replace(/^in\s+/i, "");
    const cut = after.search(/\b(?:vol(?:ume)?\.?|no\.?|iss(?:ue)?\.?|pp?\.?|doi:|(?:19|20)\d{2})\b/i);
    item.container = (cut >= 0 ? after.slice(0, cut) : after).replace(/[,\s]+$/, "").trim();
  } else {
    const bits = text.split(/\.\s+/);
    if (bits.length >= 2) {
      item.authors = bits[0];
      item.title = bits[1].replace(/[“"]/g, "").replace(/[,\s]+$/, "");
      const rest = bits.slice(2).join(". ");
      const cut = rest.search(/\b(?:vol(?:ume)?\.?|pp?\.?|(?:19|20)\d{2}|press|publisher)\b/i);
      item.container = (cut >= 0 ? rest.slice(0, cut) : rest).replace(/[,\s]+$/, "").trim();
    } else {
      item.title = text;
    }
  }
  const probe = `${item.container} ${text} ${item.raw}`;
  item.kind = detectKind(probe);
  if (item.kind !== "journal") {
    const press = probe.match(/([A-Z][^,]{2,60}(?:Press|Publisher|Publishing))/);
    if (press) item.publisher = press[1].trim();
    const city = probe.match(/\b([A-Z][A-Za-z.\s]+?)\s*:\s*[A-Z][^,]{2,40}(?:Press|Publisher|Publishing)/);
    if (city) item.city = city[1].trim();
  }
  item.extra = leftoverOf(item.raw, item);
  return item;
}

function authorsOf(item: ReferenceItem): ParsedAuthor[] {
  return parseAuthorList(item.authors);
}

function dated(item: ReferenceItem): string {
  return [item.month, item.year].filter(Boolean).join(" ");
}

function withUrl(line: string, item: ReferenceItem): string {
  if (!item.url || line.includes(item.url)) return line;
  return `${line.replace(/[.\s]+$/, "")}. ${item.url}`;
}

function withRest(line: string, item: ReferenceItem): string {
  const withLink = withUrl(line, item);
  const extra = (item.extra || "").trim();
  if (!extra) return withLink;
  if (withLink.toLowerCase().includes(extra.toLowerCase())) return withLink;
  return `${withLink.replace(/[.\s]+$/, "")}, ${extra}.`;
}

export function formatReference(item: ReferenceItem, style: ReferenceStyleId, index: number): string {
  const authors = authorsOf(item);
  const doi = doiLink(item.doi);
  const pages = pagesDash(item.pages);
  const title = item.title.trim();
  const container = item.container.trim();
  const year = dated(item);

  if (style === "ieee") {
    const who = ieeeAuthors(authors);
    if (item.kind === "book") {
      const place = [item.city, item.publisher].filter(Boolean).join(": ");
      return withRest(`[${index}] ${[who, title && `${title}.`, place, year].filter(Boolean).join(", ")}${doi ? `, doi: ${doi}` : ""}.`.replace(".,", "."), item);
    }
    if (item.kind === "conference") {
      return withRest(`[${index}] ${who}, “${title},” in ${container}${year ? `, ${year}` : ""}${pages ? `, pp. ${pages}` : ""}${doi ? `, doi: ${doi}` : ""}.`, item);
    }
    const vol = item.volume ? `vol. ${item.volume}` : "";
    const no = item.issue ? `no. ${item.issue}` : "";
    const tail = [vol, no, pages ? `pp. ${pages}` : "", year, doi ? `doi: ${doi}` : ""].filter(Boolean).join(", ");
    return withRest(`[${index}] ${who}, “${title},” ${container}${tail ? `, ${tail}` : ""}.`, item);
  }

  if (style === "apa") {
    const who = apaAuthors(authors);
    if (item.kind === "book") {
      return withRest(`${who} (${year}). ${title}. ${[item.publisher, doi && `https://doi.org/${doi}`].filter(Boolean).join(". ")}`.trim(), item);
    }
    if (item.kind === "conference") {
      return withRest(`${who} (${year}). ${title}. ${container}${pages ? ` (pp. ${pages})` : ""}.${doi ? ` https://doi.org/${doi}` : ""}`, item);
    }
    const loc = [item.volume && item.issue ? `${item.volume}(${item.issue})` : item.volume, pages].filter(Boolean).join(", ");
    return withRest(`${who} (${year}). ${title}. ${container}${loc ? `, ${loc}` : ""}.${doi ? ` https://doi.org/${doi}` : ""}`, item);
  }

  if (style === "chicago") {
    const who = chicagoAuthors(authors);
    if (item.kind === "book") {
      return withRest(`${who}. ${year}. ${title}. ${[item.city, item.publisher].filter(Boolean).join(": ")}.`, item);
    }
    if (item.kind === "conference") {
      return withRest(`${who}. ${year}. “${title}.” In ${container}${pages ? `, ${pages}` : ""}.`, item);
    }
    const loc = [item.volume, item.issue ? `(${item.issue})` : "", pages ? `: ${pages}` : ""].join(" ").replace(/\s+/g, " ").trim();
    return withRest(`${who}. ${year}. “${title}.” ${container}${loc ? ` ${loc}` : ""}.${doi ? ` https://doi.org/${doi}.` : ""}`, item);
  }

  if (style === "vancouver") {
    const who = vancouverAuthors(authors);
    if (item.kind === "book") {
      return withRest(`${index}. ${who}. ${title}. ${[item.city, item.publisher].filter(Boolean).join(": ")}; ${year}.`, item);
    }
    const loc = `${year}${item.volume ? `;${item.volume}` : ""}${item.issue ? `(${item.issue})` : ""}${pages ? `:${pages}` : ""}`;
    return withRest(`${index}. ${who}. ${title}. ${container}. ${loc}.${doi ? ` doi: ${doi}.` : ""}`, item);
  }

  if (style === "harvard") {
    const who = harvardAuthors(authors);
    if (item.kind === "book") {
      return withRest(`${who} (${year}) ${title}. ${[item.city, item.publisher].filter(Boolean).join(": ")}.`, item);
    }
    const loc = [item.volume && item.issue ? `${item.volume}(${item.issue})` : item.volume, pages ? `pp. ${pages}` : ""].filter(Boolean).join(", ");
    return withRest(`${who} (${year}) '${title}', ${container}${loc ? `, ${loc}` : ""}.${doi ? ` doi: ${doi}.` : ""}`, item);
  }

  const who = mlaAuthors(authors);
  if (item.kind === "book") {
    return withRest(`${who}. ${title}. ${[item.publisher, year].filter(Boolean).join(", ")}.`, item);
  }
  const loc = [item.volume ? `vol. ${item.volume}` : "", item.issue ? `no. ${item.issue}` : "", year, pages ? `pp. ${pages}` : ""].filter(Boolean).join(", ");
  return withRest(`${who}. “${title}.” ${container}${loc ? `, ${loc}` : ""}.${doi ? ` doi:${doi}.` : ""}`, item);
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
