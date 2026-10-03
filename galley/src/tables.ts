export function parseTable(input: string): string[][] {
  const trimmed = input.trim();
  if (!trimmed) return [];
  if (/<table[\s>]/i.test(trimmed)) {
    const rows = [...trimmed.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)];
    return rows
      .map((row) =>
        [...row[1].matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi)].map((cell) =>
          cell[1]
            .replace(/<br\s*\/?>/gi, " ")
            .replace(/<[^>]+>/g, "")
            .replace(/&nbsp;/g, " ")
            .replace(/&amp;/g, "&")
            .replace(/&lt;/g, "<")
            .replace(/&gt;/g, ">")
            .replace(/\s+/g, " ")
            .trim(),
        ),
      )
      .filter((row) => row.some((cell) => cell));
  }
  const lines = trimmed.split(/\r?\n/).map((line) => line.trimEnd()).filter((line) => line.trim());
  const tabbed = lines.some((line) => line.includes("\t"));
  return lines.map((line) => (tabbed ? line.split("\t") : line.split(/\s{2,}/)).map((cell) => cell.trim()));
}
