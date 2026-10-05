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

export function currentYear(): number {
  return new Date().getFullYear();
}

export function clampDateToCurrentEra(iso: string): string {
  const match = /^(\d{4,})-(\d{2})-(\d{2})$/.exec((iso || "").trim());
  if (!match) return "";
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return "";
  const now = currentYear();
  const useYear = year >= 1990 && year <= now + 1 ? year : now;
  return `${String(useYear).padStart(4, "0")}-${match[2]}-${match[3]}`;
}

export function authorCitationName(fullName: string): string {
  const parts = fullName.trim().replace(/\./g, " ").split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "";
  const cap = (word: string) => word.charAt(0).toUpperCase() + word.slice(1);
  const letterCount = (word: string) => word.replace(/[^A-Za-z]/g, "").length;
  const initialish = (word: string) => letterCount(word) <= 1;
  if (parts.length === 1) return cap(parts[0]);
  const trailingInitials = parts.slice(1).filter(initialish).length;
  if (trailingInitials >= Math.max(2, parts.length - 2) && initialish(parts[parts.length - 1])) {
    const surname = cap(parts[0]);
    const initials = parts
      .slice(1, 4)
      .map((part) => part.replace(/[^A-Za-z]/g, "").charAt(0).toUpperCase())
      .filter(Boolean);
    return initials.length ? `${surname}. ${initials.join(". ")}` : surname;
  }
  const surname = cap(parts[parts.length - 1]);
  const given = parts.slice(0, -1).slice(0, 3);
  const initials = given.map((part) => part.replace(/[^A-Za-z]/g, "").charAt(0).toUpperCase()).filter(Boolean);
  return initials.length ? `${surname}. ${initials.join(". ")}` : surname;
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
  const clean = clampDateToCurrentEra(iso);
  if (!clean) return "";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(clean);
  if (!match) return "";
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
  if (month < 1 || month > 12) return "";
  return `${names[month - 1]} ${String(day).padStart(2, "0")}, ${year}`;
}

export function formatMonthYear(iso: string): string {
  const long = formatLongDate(iso);
  const match = /^([A-Za-z]+)\s+\d{2},\s+(\d{4})$/.exec(long);
  if (match) return `${match[1]} ${match[2]}`;
  const now = new Date();
  return now.toLocaleString("en-US", { month: "long", year: "numeric" });
}

export function displayTableCaption(caption: string, number: number): string {
  let trimmed = caption.trim();
  while (/^tables?\s*\d+[.:)]?\s*/i.test(trimmed)) {
    trimmed = trimmed.replace(/^tables?\s*\d+[.:)]?\s*/i, "").trim();
  }
  return trimmed ? `Table ${number}. ${trimmed}` : `Table ${number}.`;
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
  height += 0.28;
  if (input.topIconCount > 0) height += 0.62;
  if (input.hasIssn) height += 0.28;
  height += textLines(input.title, 48) * (16 / 72) * 1.15 + 0.06;
  height += 0.22;
  height += Math.max(1, input.affiliationCount) * 0.22;
  height += 0.2;
  height += textLines(input.citation) * LINE_IN + 0.08;
  height += 0.28;
  height += textLines(input.abstract, 78) * LINE_IN + 0.1;
  height += textLines(input.keywords ? `Keywords: ${input.keywords}` : "Keywords:") * LINE_IN + 0.08;
  height += Math.ceil(Math.max(input.partnerCount, 1) / 5) * 0.45;
  height += 0.42;
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
      return Math.min(28, Math.max(10, Math.round((block.heightPx || 220) / 20))) + textLines(block.caption, 60);
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
  const headingLike = (block: BodyBlock) =>
    block.type === "heading" || (block.type === "section" && Boolean(block.heading));
  const stretchLastFigure = (leftover: number) => {
    const last = current[current.length - 1];
    if (!last || last.type !== "figure" || leftover < 2) return;
    const extraPx = leftover * 20;
    current[current.length - 1] = { ...last, heightPx: (last.heightPx || 220) + extraPx };
    lines += leftover;
  };
  for (let index = 0; index < blocks.length; index += 1) {
    const block = blocks[index];
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
    const next = blocks[index + 1];
    const follow = headingLike(block) && next && next.type !== "pageBreak" ? Math.min(4, linesForBlock(next)) : 0;
    if (lines > 0 && lines + need + follow > PAGE.linesPerPortraitPage) {
      stretchLastFigure(PAGE.linesPerPortraitPage - lines);
      flush();
    }
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
