import type { Author, BodyBlock, IconAsset } from "./types";

export const PAGE = {
  widthIn: 7.5,
  bodyHeightIn: 10,
  marginLeftIn: 1,
  marginRightIn: 0.5,
  marginTopIn: 0.06,
  marginBottomIn: 0.5,
  charsPerLine: 78,
  linesPerPortraitPage: 48,
};

const LINE_IN = 12 / 72;

export function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function authorCitationName(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "";
  const cap = (word: string) => word.charAt(0).toUpperCase() + word.slice(1);
  if (parts.length === 1) return cap(parts[0]);
  const surname = cap(parts[parts.length - 1]);
  const initials = parts
    .slice(0, -1)
    .map((part) => part.charAt(0).toUpperCase())
    .filter(Boolean);
  return `${surname}. ${initials.join(". ")}`;
}

export type NumberedAuthor = Author & { affiliationNo: number };

export function numberAuthors(authors: Author[]): { authors: NumberedAuthor[]; affiliations: string[] } {
  const indexByKey = new Map<string, number>();
  const affiliations: string[] = [];
  const numbered = authors
    .filter((author) => author.name.trim() || author.affiliation.trim())
    .map((author) => {
      const key = author.affiliation.trim().toLowerCase();
      let affiliationNo = key ? indexByKey.get(key) : undefined;
      if (!affiliationNo) {
        affiliations.push(author.affiliation.trim());
        affiliationNo = affiliations.length;
        if (key) indexByKey.set(key, affiliationNo);
      }
      return { ...author, affiliationNo };
    });
  return { authors: numbered, affiliations };
}

export function formatLongDate(iso: string): string {
  if (!iso) return "";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const names = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
  ];
  if (month < 1 || month > 12) return iso;
  return `${names[month - 1]} ${String(day).padStart(2, "0")}, ${year}`;
}

export function formatMonthYear(iso: string): string {
  const long = formatLongDate(iso);
  const match = /^([A-Za-z]+)\s+\d{2},\s+(\d{4})$/.exec(long);
  if (!match) return long;
  return `${match[1]} ${match[2]}`;
}

export function buildCitation(input: {
  authors: Author[];
  title: string;
  journal: string;
  volume: string;
  issue: string;
  startPage: number | null;
  endPage: number | null;
  published: string;
  doi: string;
}): string {
  const names = numberAuthors(input.authors)
    .authors
    .map((author) => authorCitationName(author.name))
    .filter(Boolean);
  const who = names.length ? names.join(", ") : "Author";
  const title = input.title.trim() || "Title";
  const journal = input.journal.trim() || "Journal";
  const volume = input.volume.trim() || "00";
  const issue = input.issue.trim() || "00";
  const start = input.startPage ?? 0;
  const end = input.endPage ?? start;
  const pages = start > 0 ? `pp ${start}-${end || start}` : "";
  const month = formatMonthYear(input.published);
  const doi = input.doi.trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "");
  return [who, `“${title}”`, journal, `Vol. ${volume}`, `Issue ${issue}`, pages, month, doi ? `https://doi.org/${doi}` : ""]
    .filter(Boolean)
    .join(", ");
}

export function dateLine(dates: {
  received: string;
  revised: string;
  accepted: string;
  published: string;
}): string {
  const part = (label: string, iso: string) => `${label} | ${formatLongDate(iso) || "—"}`;
  return [
    part("Received", dates.received),
    part("Revised", dates.revised),
    part("Accepted", dates.accepted),
    part("Published", dates.published),
  ].join("  ");
}

function textLines(text: string, chars = PAGE.charsPerLine): number {
  const value = text.trim();
  if (!value) return 1;
  return Math.max(1, Math.ceil(value.length / chars));
}

export function firstPageHeightInches(input: {
  title: string;
  affiliationCount: number;
  citation: string;
  abstract: string;
  keywords: string;
  topIconCount: number;
  partnerCount: number;
  hasIssn: boolean;
}): number {
  let height = PAGE.marginTopIn + PAGE.marginBottomIn;
  height += 0.42;
  if (input.topIconCount > 0) height += 0.85;
  if (input.hasIssn) height += 0.28;
  height += textLines(input.title, 48) * (16 / 72) * 1.25 + 0.15;
  height += 0.3;
  height += Math.max(1, input.affiliationCount) * 0.24;
  height += 0.24;
  height += textLines(input.citation) * LINE_IN + 0.1;
  height += 0.32;
  const abstractLines = textLines(input.abstract, 70);
  height += Math.max(0.55, abstractLines * LINE_IN) + 0.16;
  height += textLines(input.keywords ? `Keywords: ${input.keywords}` : "Keywords:") * LINE_IN + 0.12;
  height += Math.ceil(input.partnerCount / 5) * 0.62;
  height += 1.15;
  return Math.round(height * 100) / 100;
}

export function linesForBlock(block: BodyBlock): number {
  switch (block.type) {
    case "heading":
      return 2;
    case "section":
      return 2 + textLines(block.text);
    case "paragraph":
    case "referenceLine":
      return textLines(block.text);
    case "figure":
      return 16 + textLines(block.caption, 60);
    case "table":
      return Math.min(PAGE.linesPerPortraitPage, 2 + block.rows.length * 2 + textLines(block.caption, 60));
    case "equation":
      return 2;
    case "pageBreak":
      return 0;
  }
}

export type FlowPage =
  | { kind: "portrait"; blocks: BodyBlock[] }
  | { kind: "landscape"; block: Extract<BodyBlock, { type: "table" }> };

export function flowBody(blocks: BodyBlock[]): FlowPage[] {
  const pages: FlowPage[] = [];
  let current: BodyBlock[] = [];
  let lines = 0;
  const flush = () => {
    if (current.length === 0) return;
    pages.push({ kind: "portrait", blocks: current });
    current = [];
    lines = 0;
  };
  for (const block of blocks) {
    if (block.type === "pageBreak") {
      flush();
      continue;
    }
    if (block.type === "table" && block.landscape) {
      flush();
      pages.push({ kind: "landscape", block });
      continue;
    }
    const need = linesForBlock(block);
    if (lines > 0 && lines + need > PAGE.linesPerPortraitPage) flush();
    current.push(block);
    lines += need;
  }
  flush();
  return pages;
}

export function endPageNumber(startPage: number, bodyPages: number): number {
  if (!Number.isFinite(startPage) || startPage < 1) return 0;
  return startPage + bodyPages;
}

export function parseStartPage(value: string): number | null {
  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const number = Number(trimmed);
  if (number < 1) return null;
  return number;
}

export function countFigures(blocks: BodyBlock[]): number {
  return blocks.filter((block) => block.type === "figure").length;
}

export function countTables(blocks: BodyBlock[]): number {
  return blocks.filter((block) => block.type === "table").length;
}

export function figureNumber(blocks: BodyBlock[], id: string): number {
  return blocks.filter((block) => block.type === "figure").findIndex((block) => block.id === id) + 1;
}

export function tableNumber(blocks: BodyBlock[], id: string): number {
  return blocks.filter((block) => block.type === "table").findIndex((block) => block.id === id) + 1;
}

export function cloneIcons(icons: IconAsset[]): IconAsset[] {
  return icons.map((icon) => ({ ...icon }));
}
