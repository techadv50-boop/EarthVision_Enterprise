import type { BodyBlock, ReferenceItem, ReferenceStyleId } from "./types";
import { parseAuthorList } from "./references";

export type CitationAudit = {
  missingInReferences: string[];
  unusedReferences: string[];
};

type Part = {
  ref: ReferenceItem | null;
  index: number;
  label: string;
  narrative: boolean;
};

type Span = { start: number; end: number; parts: Part[] };

function families(item: ReferenceItem): string[] {
  return parseAuthorList(item.authors)
    .map((author) => author.family.toLowerCase().replace(/\./g, ""))
    .filter(Boolean);
}

function leadName(item: ReferenceItem): string {
  const family = parseAuthorList(item.authors)[0]?.family || "Author";
  return family.charAt(0).toUpperCase() + family.slice(1);
}

function people(item: ReferenceItem, joiner: string): string {
  const names = parseAuthorList(item.authors).map((author) => author.family).filter(Boolean);
  const shown = names.map((name) => name.charAt(0).toUpperCase() + name.slice(1));
  if (shown.length >= 3) return `${shown[0]} et al.`;
  if (shown.length === 2) return `${shown[0]} ${joiner} ${shown[1]}`;
  return shown[0] || "Author";
}

function yearOf(item: ReferenceItem): string {
  return item.year || "";
}

function expandNumbers(body: string): number[] {
  const numbers: number[] = [];
  body.split(/\s*,\s*/).forEach((piece) => {
    const range = piece.match(/^(\d+)\s*[-–—]\s*(\d+)$/);
    if (range) {
      const from = Number(range[1]);
      const to = Number(range[2]);
      const span = Math.abs(to - from);
      if (span > 30) return;
      const step = from <= to ? 1 : -1;
      for (let value = from; step > 0 ? value <= to : value >= to; value += step) numbers.push(value);
      return;
    }
    if (/^\d+$/.test(piece)) numbers.push(Number(piece));
  });
  return numbers;
}

function byNumber(value: number, references: ReferenceItem[]): Part {
  const ref = references[value - 1] || null;
  return { ref, index: value, label: String(value), narrative: false };
}

function byName(
  name: string,
  second: string | undefined,
  etAl: boolean,
  year: string,
  references: ReferenceItem[],
  narrative: boolean,
): Part {
  const lead = name.toLowerCase();
  const other = second?.toLowerCase();
  const ref =
    references.find((item) => {
      const names = families(item);
      if (!names.length || names[0] !== lead) return false;
      if (item.year.slice(0, 4) !== year.slice(0, 4)) return false;
      if (other && !names.includes(other)) return false;
      if (etAl && names.length < 2) return false;
      return true;
    }) || null;
  const label = `${name}${etAl ? " et al." : second ? ` and ${second}` : ""}, ${year}`;
  return { ref, index: ref ? references.indexOf(ref) + 1 : 0, label, narrative };
}

function collapse(indexes: number[]): string {
  const sorted = [...new Set(indexes)].sort((left, right) => left - right);
  const parts: string[] = [];
  let start = sorted[0];
  let previous = sorted[0];
  for (let cursor = 1; cursor <= sorted.length; cursor += 1) {
    const value = sorted[cursor];
    if (value === previous + 1) {
      previous = value;
      continue;
    }
    parts.push(start === previous ? String(start) : `${start}-${previous}`);
    start = value;
    previous = value;
  }
  return parts.join(", ");
}

function renderParts(parts: Part[], style: ReferenceStyleId): string {
  const narrative = parts.length === 1 && parts[0].narrative;
  if (style === "ieee" || style === "vancouver") {
    const body = collapse(parts.map((part) => part.index));
    const wrapped = style === "ieee" ? `[${body}]` : `(${body})`;
    return narrative ? `${leadName(parts[0].ref as ReferenceItem)} ${wrapped}` : wrapped;
  }
  const joiner = style === "apa" ? "&" : "and";
  const bits = parts.map((part) => {
    const item = part.ref as ReferenceItem;
    const who = people(item, joiner);
    const year = yearOf(item);
    if (style === "mla") return who;
    if (style === "chicago") return year ? `${who} ${year}` : who;
    return year ? `${who}, ${year}` : who;
  });
  if (narrative) {
    const item = parts[0].ref as ReferenceItem;
    const who = people(item, joiner);
    const year = yearOf(item);
    if (style === "mla") return who;
    return year ? `${who} (${year})` : who;
  }
  return `(${bits.join("; ")})`;
}

function collect(text: string, references: ReferenceItem[]): Span[] {
  const spans: Span[] = [];
  const take = (start: number, end: number, parts: Part[]) => {
    if (!parts.length) return;
    if (spans.some((span) => start < span.end && end > span.start)) return;
    spans.push({ start, end, parts });
  };

  for (const match of text.matchAll(/\[(\d+(?:\s*[-–—]\s*\d+)?(?:\s*,\s*\d+(?:\s*[-–—]\s*\d+)?)*)\]/g)) {
    take(match.index || 0, (match.index || 0) + match[0].length, expandNumbers(match[1]).map((value) => byNumber(value, references)));
  }
  for (const match of text.matchAll(/\((\d+(?:\s*[-–—]\s*\d+)?(?:\s*,\s*\d+(?:\s*[-–—]\s*\d+)?)*)\)/g)) {
    const numbers = expandNumbers(match[1]).filter((value) => value < 1900);
    if (!numbers.length) continue;
    take(match.index || 0, (match.index || 0) + match[0].length, numbers.map((value) => byNumber(value, references)));
  }
  for (const match of text.matchAll(/\(([^()\n]{2,220})\)/g)) {
    const pieces = match[1].split(/\s*;\s*/);
    const parts = pieces.map((piece) => {
      const found = piece
        .trim()
        .match(/^(?:e\.g\.,?\s+|see\s+)?([A-Z][A-Za-z'’\-]+)(\s+et\s+al\.?)?(?:\s+(?:and|&)\s+([A-Z][A-Za-z'’\-]+))?\s*,\s*((?:19|20)\d{2}[a-z]?)$/i);
      if (!found) return null;
      return byName(found[1], found[3], Boolean(found[2]), found[4], references, false);
    });
    if (parts.some((part) => !part)) continue;
    take(match.index || 0, (match.index || 0) + match[0].length, parts.filter((part): part is Part => Boolean(part)));
  }
  for (const match of text.matchAll(
    /\b([A-Z][A-Za-z'’\-]+)(\s+et\s+al\.?)?(?:\s+(?:and|&)\s+([A-Z][A-Za-z'’\-]+))?\s+\(((?:19|20)\d{2}[a-z]?)\)/g,
  )) {
    take(match.index || 0, (match.index || 0) + match[0].length, [
      byName(match[1], match[3], Boolean(match[2]), match[4], references, true),
    ]);
  }
  return spans.sort((left, right) => left.start - right.start);
}

export function stitchText(
  text: string,
  references: ReferenceItem[],
  style: ReferenceStyleId,
): { text: string; missing: string[]; used: Set<string> } {
  const missing: string[] = [];
  const used = new Set<string>();
  let next = text;
  const spans = collect(text, references).sort((left, right) => right.start - left.start);
  spans.forEach((span) => {
    span.parts.forEach((part) => {
      if (part.ref) used.add(part.ref.id);
      else missing.push(part.label);
    });
    if (span.parts.every((part) => part.ref)) {
      next = next.slice(0, span.start) + renderParts(span.parts, style) + next.slice(span.end);
    }
  });
  return { text: next, missing, used };
}

function eachText(blocks: BodyBlock[], visit: (text: string) => void): void {
  blocks.forEach((block) => {
    if (block.type === "section") {
      visit(block.heading);
      visit(block.text);
    } else if (block.type === "paragraph" || block.type === "heading") visit(block.text);
  });
}

export function stitchBlocks(blocks: BodyBlock[], references: ReferenceItem[], style: ReferenceStyleId): BodyBlock[] {
  const apply = (text: string) => stitchText(text, references, style).text;
  return blocks.map((block) => {
    if (block.type === "section") return { ...block, heading: apply(block.heading), text: apply(block.text) };
    if (block.type === "paragraph" || block.type === "heading") return { ...block, text: apply(block.text) };
    return block;
  });
}

export function auditCitations(blocks: BodyBlock[], references: ReferenceItem[]): CitationAudit {
  const missing: string[] = [];
  const used = new Set<string>();
  eachText(blocks, (text) => {
    collect(text, references).forEach((span) => {
      span.parts.forEach((part) => {
        if (part.ref) used.add(part.ref.id);
        else missing.push(part.label);
      });
    });
  });
  const unusedReferences = references
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item.authors || item.title || item.raw)
    .filter(({ item }) => !used.has(item.id))
    .map(({ item, index }) => {
      const who = parseAuthorList(item.authors)
        .map((author) => author.family)
        .filter(Boolean)
        .join(", ");
      return `${index + 1}. ${[who, item.year, item.title].filter(Boolean).join(", ") || item.raw}`;
    });
  return { missingInReferences: [...new Set(missing)], unusedReferences };
}
