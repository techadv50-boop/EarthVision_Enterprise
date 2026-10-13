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

function stripReferenceNumber(blob: string): string {
  return blob.replace(/^\s*(?:\[\d+\]|\d+[.)]|\d+)\s+/, "").trim();
}

function isJunkReference(blob: string): boolean {
  const compact = stripReferenceNumber(blob).replace(/[“”"'\s,.:;]+/g, "").toLowerCase();
  return !compact || compact === "references" || compact === "refrences" || compact === "bibliography";
}

function looksLikeName(after: string): boolean {
  const text = after.replace(/^(?:and\s+)/i, "");
  if (/^[A-Z]{3,}\b/.test(text)) return true;
  return /^(?:(?:[A-ZÀ-ž]\.\s*){1,4}|[A-ZÀ-ž](?:\s+[A-ZÀ-ž]){0,3}\s+)[A-ZÀ-ž][A-Za-zÀ-ž'’\-]{1,}/.test(text);
}

function looksLikeAuthorAfterNumber(chunk: string, digitIndex: number): boolean {
  const before = chunk.slice(Math.max(0, digitIndex - 16), digitIndex);
  if (/\b(?:vol(?:ume)?|no|iss(?:ue)?|pp?|art(?:icle)?\s*no\.?)\s*$/i.test(before)) return false;
  const after = chunk.slice(digitIndex).replace(/^\d{1,3}\s+/, "");
  return looksLikeName(after);
}

function splitInlineNumbered(chunk: string): string[] {
  const hits: { index: number; n: number }[] = [];
  for (const match of chunk.matchAll(/\[\d+\]/g)) {
    hits.push({ index: match.index || 0, n: Number(match[0].slice(1, -1)) });
  }
  for (const match of chunk.matchAll(/\b(\d{1,3})\s+/g)) {
    const n = Number(match[1]);
    if (n < 1 || n > 400) continue;
    const digitIndex = match.index || 0;
    if (!looksLikeAuthorAfterNumber(chunk, digitIndex)) continue;
    hits.push({ index: digitIndex, n });
  }
  hits.sort((left, right) => left.index - right.index);
  const kept: { index: number; n: number }[] = [];
  for (const hit of hits) {
    const last = kept[kept.length - 1];
    if (last && hit.index - last.index < 6) continue;
    if (!last || hit.n >= last.n) kept.push(hit);
  }
  if (kept.length <= 1) return [chunk.trim()].filter(Boolean);
  const parts: string[] = [];
  if (kept[0].index > 0) {
    const head = chunk.slice(0, kept[0].index).trim();
    if (head && !isJunkReference(head)) parts.push(head);
  }
  for (let index = 0; index < kept.length; index += 1) {
    const end = index + 1 < kept.length ? kept[index + 1].index : chunk.length;
    const slice = chunk.slice(kept[index].index, end).trim();
    if (slice) parts.push(slice);
  }
  return parts;
}

export function splitReferenceBlob(raw: string): string[] {
  const trimmed = raw.replace(/\r\n/g, "\n").trim();
  if (!trimmed) return [];
  const blankBlocks = trimmed
    .split(/\n\s*\n/)
    .map((part) => part.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  const lineBlocks = trimmed
    .split(/\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const numberedLines = lineBlocks.filter((line) => /^(\[\d+\]|\d+[.)])\s*/.test(line));
  const seed = numberedLines.length >= 2 ? lineBlocks : blankBlocks.length > 1 ? blankBlocks : [trimmed.replace(/\s+/g, " ").trim()];
  const parts: string[] = [];
  for (const block of seed) {
    parts.push(...splitInlineNumbered(block));
  }
  return parts.filter((part) => part && !isJunkReference(part));
}

export function segregateReferences(raw: string): ReferenceItem[] {
  return splitReferenceBlob(raw).map((blob) => parseReference(blob));
}

function isReferencesHeading(text: string): boolean {
  return /^references\b/i.test(text.replace(/[:\s]+$/g, "").trim());
}

export function splitBodyAndReferences(blocks: BodyBlock[]): { body: BodyBlock[]; referenceText: string } {
  const body: BodyBlock[] = [];
  const texts: string[] = [];
  let take = false;
  for (const block of blocks) {
    const heading = block.type === "section" ? block.heading : block.type === "heading" ? block.text : "";
    if (isReferencesHeading(heading) || block.type === "referenceLine") {
      take = true;
      if (block.type === "section" && block.text.trim()) texts.push(block.text);
      else if (block.type === "referenceLine" || block.type === "heading") {
        if (block.type === "referenceLine" && block.text.trim()) texts.push(block.text);
      }
      continue;
    }
    if (take) {
      if (block.type === "paragraph" || block.type === "heading") {
        if (block.text.trim()) texts.push(block.text);
        continue;
      }
      if (block.type === "section") {
        const text = [block.heading, block.text].filter(Boolean).join(" ");
        if (text.trim()) texts.push(text);
        continue;
      }
    }
    body.push(block);
  }
  return { body, referenceText: texts.join("\n\n").trim() };
}

export function referenceTextFromBlocks(blocks: BodyBlock[]): string {
  return splitBodyAndReferences(blocks).referenceText;
}

export function withoutReferenceSection(blocks: BodyBlock[]): BodyBlock[] {
  return splitBodyAndReferences(blocks).body;
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

function parseIeeeAuthorRun(raw: string): ParsedAuthor[] {
  const cleaned = raw.replace(/\bet\s*al\.?/gi, " ").replace(/\s+and\s+/gi, " ").replace(/[.,\s]+$/, "").trim();
  if (!cleaned) return [];
  const authors: ParsedAuthor[] = [];
  const pattern = /([A-Z](?:\.[A-Z])*\.?(?:\s+[A-Z](?:\.[A-Z])*\.?)*)\s+([A-ZÀ-ž][A-Za-zÀ-ž'’\-]+)/g;
  for (const match of cleaned.matchAll(pattern)) {
    authors.push({ given: match[1].replace(/\s+/g, " ").trim(), family: match[2] });
  }
  return authors;
}

export function parseAuthorList(raw: string): ParsedAuthor[] {
  const cleaned = raw.replace(/\bet\s*al\.?/gi, " ").replace(/\s+and\s+/gi, ", ").replace(/[.,\s]+$/, "");
  if (!cleaned.trim()) return [];
  if (!cleaned.includes(",")) {
    const run = parseIeeeAuthorRun(raw);
    if (run.length) return run;
  }
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
    const ieee = parseIeeeAuthorRun(token);
    if (ieee.length > 1 || (ieee.length === 1 && /^(?:[A-Z]\.?\s+){1,3}[A-ZÀ-ž]/.test(token))) {
      authors.push(...ieee);
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
  let rest = stripReferenceNumber(original);
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
    item.issue ? `no ${item.issue}` : "",
    item.issue ? `issue ${item.issue}` : "",
    item.issue,
    item.pages ? `pp. ${item.pages}` : "",
    item.pages ? `pp ${item.pages}` : "",
    item.pages ? `p ${item.pages}` : "",
    item.pages,
    item.year,
    item.month,
    item.doi,
    item.url,
  ].filter(Boolean);
  pieces.sort((left, right) => right.length - left.length);
  for (const piece of pieces) {
    const escaped = piece.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    rest = rest.replace(new RegExp(escaped, "i"), " ");
  }
  rest = rest.replace(/\b(doi:|https?:\/\/(?:dx\.)?doi\.org\/|vol(?:ume)?\.?|iss(?:ue)?\.?|pp\.?)\b/gi, " ");
  rest = rest.replace(/[“”"'[\]()]/g, " ").replace(/[.,;:/]+/g, " ").replace(/\s+/g, " ").trim();
  return rest;
}

const MONTHS: Record<string, string> = {
  january: "January",
  jan: "January",
  february: "February",
  feb: "February",
  march: "March",
  mar: "March",
  april: "April",
  apr: "April",
  may: "May",
  june: "June",
  jun: "June",
  july: "July",
  jul: "July",
  august: "August",
  aug: "August",
  september: "September",
  sep: "September",
  sept: "September",
  october: "October",
  oct: "October",
  november: "November",
  nov: "November",
  december: "December",
  dec: "December",
};

function pullDoi(text: string): { doi: string; text: string } {
  const dotted = text.match(/(?:doi:\s*)?(?:https?:\/\/(?:dx\.)?doi\.org\/)?(10\.\d{4,9}\/[^\s,;]+)/i);
  if (dotted) {
    return { doi: dotted[1].replace(/[.)]+$/, ""), text: text.replace(dotted[0], " ") };
  }
  const spaced = text.match(/\bdoi:?\s+10\s+(\d{4,9})\s+([A-Za-z0-9][A-Za-z0-9._\-]*(?:\s+[A-Za-z0-9._\-]+)*)/i);
  if (!spaced) return { doi: "", text };
  return {
    doi: `10.${spaced[1]}/${spaced[2].trim().split(/\s+/).join(".")}`,
    text: text.replace(spaced[0], " "),
  };
}

function isYearish(value: string): boolean {
  const number = Number(value);
  return number >= 1800 && number <= 2100;
}

function takeTrailingJournal(before: string): { container: string; head: string } {
  const tokens = before.trim().split(/\s+/).filter(Boolean);
  const journal: string[] = [];
  const glue = /^(of|and|the|in|for|&)$/i;
  const cueWord = /^(Journal|Journals|Revue|Review|Proceedings|Transactions|Letters|Reports|Annals|Archives|Bulletin)$/i;
  const strongPrefix = /^(IEEE|Int|International|Am|American|Eur|European|Br|British|Mining|Applied|Safety|Occupational|Formosa|Scientific|J)$/i;
  const skipBeforeCue = /^(A|An|The|This|Comprehensive|Short|Critical|Systematic|Narrative|Updated|Recent|New)$/i;
  const keepers = /^(Results|Applied|Safety|Mining|Occupational|Formosa|Sustainable|Human|Accident|Reliability|Resources|Scientific|Engineering|Sciences)$/i;
  for (let index = tokens.length - 1; index >= 0; index -= 1) {
    const token = tokens[index];
    if (glue.test(token) && journal.length) {
      journal.unshift(token);
      continue;
    }
    if (/^[A-ZÀ-ž]/.test(token)) {
      journal.unshift(token);
      continue;
    }
    break;
  }
  const cueIndex = journal.reduce((found, token, index) => (cueWord.test(token) ? index : found), -1);
  if (cueIndex >= 0) {
    const afterCue = journal.length - 1 - cueIndex;
    let start = cueIndex;
    if (afterCue <= 1) {
      const maxExtra = /review/i.test(journal[cueIndex]) ? 2 : 1;
      let extra = 0;
      while (start > 0 && extra < maxExtra) {
        const prev = journal[start - 1];
        if (glue.test(prev)) {
          start -= 1;
          continue;
        }
        if (skipBeforeCue.test(prev)) break;
        start -= 1;
        extra += 1;
      }
    } else {
      while (start > 0 && strongPrefix.test(journal[start - 1])) start -= 1;
    }
    journal.splice(0, start);
  } else {
    const shortCount = journal.filter((token) => token.replace(/\./g, "").length <= 4).length;
    const abbrev = journal.length > 0 && shortCount >= Math.ceil(journal.length * 0.6);
    if (!abbrev && journal.length > 1) {
      const last = journal[journal.length - 1];
      if (last.length >= 8) {
        let start = journal.length - 1;
        if (journal.length >= 3 && glue.test(journal[journal.length - 2]) && keepers.test(journal[journal.length - 3])) {
          start = journal.length - 3;
        } else if (journal.length >= 2 && keepers.test(journal[journal.length - 2])) {
          start = journal.length - 2;
        }
        journal.splice(0, start);
      }
    }
  }
  return { container: journal.join(" ").trim(), head: tokens.slice(0, tokens.length - journal.length).join(" ") };
}

function takeAuthors(head: string): { authors: string; title: string } {
  const tokens = head.trim().split(/\s+/).filter(Boolean);
  const bits: string[] = [];
  const isInitial = (token: string) => /^[A-ZÀ-ž](?:\.[A-ZÀ-ž])*\.?$/.test(token) && token.replace(/\./g, "").length <= 3;
  const isFamily = (token: string) => /^[A-ZÀ-ž][A-Za-zÀ-ž'’\-]{1,}$/.test(token) && token.replace(/[-'’]/g, "").length >= 2;
  let index = 0;
  while (index < tokens.length) {
    if (/^et$/i.test(tokens[index]) && /^al\.?$/i.test(tokens[index + 1] || "")) {
      bits.push("et al.");
      index += 2;
      break;
    }
    if (/^and$/i.test(tokens[index]) && index + 1 < tokens.length) {
      bits.push("and");
      index += 1;
      continue;
    }
    if (/^[A-Z]{3,}$/.test(tokens[index]) && bits.length === 0) {
      bits.push(tokens[index]);
      index += 1;
      continue;
    }
    const saved = index;
    const initials: string[] = [];
    while (index < tokens.length && isInitial(tokens[index])) {
      initials.push(tokens[index]);
      index += 1;
    }
    if (initials.length && index < tokens.length && isFamily(tokens[index])) {
      bits.push([...initials, tokens[index]].join(" "));
      index += 1;
      continue;
    }
    index = saved;
    break;
  }
  if (!bits.length) return { authors: "", title: head.trim() };
  return {
    authors: bits.join(", ").replace(/, and,/g, " and").replace(/, and /g, " and "),
    title: tokens.slice(index).join(" ").trim(),
  };
}

function fillUnquoted(text: string, item: ReferenceItem): void {
  const volWord = text.match(/\bvol(?:ume)?\.?\s*(\d+)/i);
  const volNo = text.match(/\b(\d{1,4})\s+no\.?\s*(\d+)/i);
  const volP = text.match(/\b(\d{1,4})\s+p\.?\s+(\d+)/i);
  const volPages = text.match(/\b(\d{1,4})\s+(\d+\s*[-–]\s*\d+)/);
  let volumeAt = -1;
  if (volWord) {
    item.volume = item.volume || volWord[1];
    volumeAt = volWord.index ?? -1;
  } else if (volNo && !isYearish(volNo[1])) {
    item.volume = item.volume || volNo[1];
    item.issue = item.issue || volNo[2];
    volumeAt = volNo.index ?? -1;
  } else if (volP && !isYearish(volP[1])) {
    item.volume = item.volume || volP[1];
    if (!item.pages) item.pages = volP[2];
    volumeAt = volP.index ?? -1;
  } else if (volPages && !isYearish(volPages[1])) {
    item.volume = item.volume || volPages[1];
    if (!item.pages) item.pages = volPages[2].replace(/\s/g, "");
    volumeAt = volPages.index ?? -1;
  }
  const before = (volumeAt >= 0 ? text.slice(0, volumeAt) : text).replace(/[,\s]+$/, "");
  const { container, head } = takeTrailingJournal(before);
  if (container) item.container = container;
  const parts = takeAuthors(head);
  if (parts.authors) item.authors = parts.authors;
  item.title = (parts.title || head || text).replace(/[,\s]+$/, "");
}

export function parseReference(raw: string): ReferenceItem {
  const item = emptyReference();
  item.raw = raw.trim();
  let text = stripReferenceNumber(raw);
  const doi = pullDoi(text);
  item.doi = doi.doi;
  text = doi.text;
  const urlMatch = text.match(/https?:\/\/[^\s,;]+/i);
  if (urlMatch && !/doi\.org/i.test(urlMatch[0])) {
    item.url = urlMatch[0].replace(/[.)]+$/, "");
    text = text.replace(urlMatch[0], " ");
  }
  const monthMatch = text.match(
    /\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\b/i,
  );
  if (monthMatch) {
    item.month = MONTHS[monthMatch[1].toLowerCase()] || monthMatch[1];
    text = text.replace(monthMatch[0], " ");
  }
  text = text.replace(/\bdoi:\s*/i, " ").replace(/\s+/g, " ").trim();
  const yearMatch = text.match(/\b((?:19|20)\d{2})\b/);
  if (yearMatch) item.year = yearMatch[1];
  const pagesMatch = text.match(/\bpp?\.?\s*(\d+\s*[-–]\s*\d+|\d+)/i) || text.match(/:\s*(\d+\s*[-–]\s*\d+)/);
  if (pagesMatch) item.pages = pagesMatch[1].replace(/\s/g, "");
  if (!item.pages) {
    const range = text.match(/\b(\d{1,4})\s*[-–]\s*(\d{1,4})\b/);
    if (range && Math.abs(Number(range[1]) - Number(range[2])) <= 250 && Number(range[1]) < 5000 && Number(range[2]) < 5000) {
      item.pages = `${range[1]}-${range[2]}`;
    }
  }
  const volIssue = text.match(/\b(\d+)\s*\((\d+)\)/);
  const vol = text.match(/\bvol(?:ume)?\.?\s*(\d+)/i);
  const issueNo = text.match(/(?<!\bart(?:icle)?\s)\bno\.?\s*(\d+)/i);
  const issueWord = text.match(/\biss(?:ue)?\.?\s*(\d+)/i);
  if (vol) item.volume = vol[1];
  if (issueNo) item.issue = issueNo[1];
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
  } else if (/\.\s+[A-Z]/.test(text)) {
    const bits = text.split(/\.\s+/);
    item.authors = bits[0];
    item.title = bits[1].replace(/[“"]/g, "").replace(/[,\s]+$/, "");
    const rest = bits.slice(2).join(". ");
    const cut = rest.search(/\b(?:vol(?:ume)?\.?|pp?\.?|(?:19|20)\d{2}|press|publisher)\b/i);
    item.container = (cut >= 0 ? rest.slice(0, cut) : rest).replace(/[,\s]+$/, "").trim();
  } else {
    fillUnquoted(text, item);
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
