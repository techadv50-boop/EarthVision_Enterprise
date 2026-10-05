import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { Packer } from "docx";
import { galleyDocument } from "./exportDocx";
import type { Galley, Journal } from "./types";

const PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

const journal: Journal = {
  id: "ijist",
  name: "International Journal of Innovations in Science & Technology",
  abbreviation: "IJIST",
  issnP: "2618-1630",
  issnE: "2618-1630",
  topIcons: [{ id: "t", name: "top", dataUrl: PNG, widthPx: 40, heightPx: 20 }],
  partnerIcons: [{ id: "p", name: "partner", dataUrl: PNG, widthPx: 40, heightPx: 16 }],
};

const galley: Galley = {
  id: "g",
  journalId: "ijist",
  title: "Heart Disease Prediction",
  authors: [
    {
      id: "a",
      name: "Romaan khan",
      affiliation: "University of Agriculture Peshawar",
      corresponding: true,
      email: "romaan@aup.edu.pk",
    },
  ],
  volume: "7",
  issue: "4",
  startPage: "2705",
  received: "2025-10-05",
  revised: "2025-10-20",
  accepted: "2025-10-26",
  published: "2025-11-08",
  doi: "10.33411/ijist/example",
  abstract: "Accurate and reliable heart disease prediction can support early risk assessment.",
  keywords: "Heart Disease; Machine Learning",
  topIcons: journal.topIcons,
  partnerIcons: journal.partnerIcons,
  references: [],
  referenceSource: "",
  referenceStyle: "ieee",
  blocks: [
    { id: "h", type: "heading", text: "Introduction:" },
    { id: "p", type: "paragraph", text: "Cardiovascular diseases remain a global burden." },
    {
      id: "t",
      type: "table",
      caption: "Table 5 Performance Comparison of This Study with Existing Techniques",
      source: "Model\tAUC\nCatBoost\t0.91",
      landscape: true,
      rows: [
        ["Author(s)", "Year", "Dataset"],
        [
          'Stamatatos et al. ADDIN CSL_CITATION {"citationItems":[{"id":"ITEM-1","itemData":{"author":[{"family":"Stamatatos"}]},"formattedCitation":"Stamatatos et al., 2009"}]}',
          "2009",
          "PAN",
        ],
      ],
    },
    { id: "r", type: "heading", text: "References:" },
    { id: "ref", type: "paragraph", text: "[1] C. Zhang, “A title,” 2026." },
  ],
  updatedAt: 1,
};

describe("Word galley", () => {
  it("writes a docx whose first section starts at the composer’s page and isolates the landscape table", async () => {
    const buffer = await Packer.toBuffer(galleyDocument(galley, journal, { id: "oa", name: "Open Access", dataUrl: PNG, widthPx: 64, heightPx: 20 }));
    const dir = mkdtempSync(join(tmpdir(), "galley-"));
    const file = join(dir, "proof.docx");
    writeFileSync(file, buffer);
    const packed = execFileSync("python3", [
      "-c",
      `import zipfile,sys
z=zipfile.ZipFile(sys.argv[1])
parts=[]
for name in z.namelist():
    if name.startswith("word/document") or name.startswith("word/header") or name.startswith("word/footer"):
        parts.append(z.read(name).decode("utf-8"))
print("\\n".join(parts))`,
      file,
    ]).toString();
    expect(packed).toContain('w:start="2705"');
    expect(packed).toContain("International Journal of Innovations in Science");
    expect(packed).toContain("Heart Disease Prediction");
    expect(packed).not.toContain("OPEN ACCESS");
    expect(packed).not.toContain("ISSN-P");
    expect(packed).toContain("E87722");
    expect(packed).toContain("Accurate and reliable heart disease prediction can support early risk assessment.");
    expect(packed).toContain("November 2025 | Vol 7 | Issue 4");
    expect(packed).toContain("Table 1.");
    expect(packed).toContain("Performance Comparison of This Study with Existing Techniques");
    expect(packed).not.toContain("Table 5");
    expect(packed).toContain("Stamatatos et al.");
    expect(packed).not.toContain("ADDIN");
    expect(packed).not.toContain("citationItems");
    expect(packed).toContain("PAGE");
    const sections = packed.split("<w:sectPr").slice(1);
    expect(sections.length).toBeGreaterThanOrEqual(3);
    expect(sections.some((section) => section.includes('w:orient="landscape"'))).toBe(true);
    const widths = [...packed.matchAll(/<w:pgSz[^>]*>/g)].map((match) => match[0]);
    expect(widths[0]).toContain('w:w="10800"');
    expect(widths.some((size) => size.includes('w:h="14400"') && size.includes('w:orient="portrait"'))).toBe(true);
    expect(packed.match(/w:start="\d+"/g)).toEqual(['w:start="2705"']);
  });
});
