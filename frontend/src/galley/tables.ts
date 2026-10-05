export function decodeTableEntities(text: string): string {
  return text
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)));
}

export function cleanTableCell(text: string): string {
  let value = decodeTableEntities(String(text || ""));
  value = value.replace(/<br\s*\/?>/gi, " ").replace(/<[^>]+>/g, " ");
  if (/ADDIN\s+CSL_CITATION/i.test(value) || /"citationItems"/i.test(value) || /citation-style-language/i.test(value)) {
    const before = value.split(/ADDIN\s+CSL_CITATION/i)[0].replace(/[{[]+\s*$/, "").trim();
    if (before && before.length < 180 && !/"id"\s*:/.test(before)) return before.replace(/\s+/g, " ").trim();
    const formatted = value.match(/"formattedCitation"\s*:\s*"((?:\\.|[^"\\])*)"/);
    if (formatted) {
      try {
        return JSON.parse(`"${formatted[1]}"`);
      } catch {
        return formatted[1].replace(/\\"/g, '"');
      }
    }
    const family = value.match(/"family"\s*:\s*"([^"]+)"/);
    const year = value.match(/"date-parts"\s*:\s*\[\s*\[\s*(\d{4})/);
    if (family) return `${family[1]}${year ? ` (${year[1]})` : ""}`;
    return "";
  }
  return value.replace(/\s+/g, " ").trim();
}

export function sanitizeTableRows(rows: string[][]): string[][] {
  return (rows || []).map((row) => row.map((cell) => cleanTableCell(cell)));
}

export function parseTable(input: string): string[][] {
  const trimmed = input.trim();
  if (!trimmed) return [];
  if (/<table[\s>]/i.test(trimmed)) {
    const rows = [...trimmed.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)];
    return rows
      .map((row) =>
        [...row[1].matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi)].map((cell) => cleanTableCell(cell[1])),
      )
      .filter((row) => row.some((cell) => cell));
  }
  const lines = trimmed.split(/\r?\n/).map((line) => line.trimEnd()).filter((line) => line.trim());
  const tabbed = lines.some((line) => line.includes("\t"));
  return lines.map((line) => (tabbed ? line.split("\t") : line.split(/\s{2,}/)).map((cell) => cleanTableCell(cell)));
}

export function columnWidths(rows: string[][]): number[] {
  const columns = Math.max(1, ...rows.map((row) => row.length));
  const header = rows[0] || [];
  const maxChars = Array.from({ length: columns }, (_, index) => Math.min(28, Math.max(header[index]?.trim().length || 1, 1)));
  for (const row of rows.slice(1)) {
    for (let index = 0; index < columns; index += 1) {
      maxChars[index] = Math.max(maxChars[index], Math.min(28, (row[index] || "").trim().length || 1));
    }
  }
  const total = maxChars.reduce((sum, value) => sum + value, 0) || columns;
  const widths = maxChars.map((value, index) => {
    const shortHeader = (header[index] || "").trim().length <= 8;
    const floor = shortHeader ? 10 : 8;
    return Math.max(floor, Math.min(48, Math.round((100 * value) / total)));
  });
  const drift = 100 - widths.reduce((sum, value) => sum + value, 0);
  widths[widths.length - 1] += drift;
  return widths;
}
