import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { auditCitations, stitchBlocks, stitchText } from "./citations";
import { segregateReferences } from "./references";
import type { BodyBlock } from "./types";

const mashed = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "fixtures/mashed-references.txt"), "utf8");
const intro = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "fixtures/mashed-intro.txt"), "utf8");

const source = `[1] R. Khan, "Wheat yield," Journal of Crops, vol. 2, no. 1, pp. 4-5, 2024.
[2] A. Ali, "Soil water," Journal of Soils, vol. 3, no. 2, pp. 8-9, 2020.
[3] B. Noor, "Unused study," Journal of Seeds, vol. 1, no. 1, pp. 1-2, 2019.`;

describe("in-text citations", () => {
  const references = segregateReferences(source);

  it("stitches a numbered citation and an author-year citation to the selected style", () => {
    const numbered = stitchText("Yield rose [1] after irrigation.", references, "apa");
    expect(numbered.text).toContain("(Khan, 2024)");
    expect(numbered.text).not.toContain("[1]");
    const named = stitchText("Khan (2024) reported the yield.", references, "ieee");
    expect(named.text).toContain("Khan [1]");
  });

  it("reports names or numbers that are not in the references, and references that are not cited", () => {
    const blocks: BodyBlock[] = [
      { id: "s", type: "section", heading: "Introduction:", text: "See [1] and [9]. Zed (1999) disagrees. Ali (2020) agrees." },
    ];
    const stitched = stitchBlocks(blocks, references, "ieee");
    const section = stitched[0];
    if (section.type !== "section") throw new Error("expected a section");
    expect(section.text).toContain("[1]");
    expect(section.text).toContain("Ali [2]");
    expect(section.text).toContain("[9]");
    expect(section.text).toContain("Zed (1999)");
    const audit = auditCitations(stitched, references);
    expect(audit.missingInReferences).toEqual(expect.arrayContaining(["9", "Zed, 1999"]));
    expect(audit.unusedReferences.some((line) => line.startsWith("3."))).toBe(true);
    expect(audit.unusedReferences.some((line) => line.startsWith("1."))).toBe(false);
  });

  it("stitches mashed numbered citations to the matching segregated reference", () => {
    const references = segregateReferences(mashed);
    const blocks: BodyBlock[] = [
      { id: "intro", type: "section", heading: "Introduction:", text: intro },
      { id: "refs", type: "section", heading: "References:", text: mashed },
    ];
    const stitched = stitchBlocks(blocks, references, "ieee");
    const section = stitched[0];
    if (section.type !== "section") throw new Error("expected a section");
    expect(section.text).toContain("[1]");
    expect(section.text).toContain("[10]");
    expect(stitched[1].type === "section" && stitched[1].text).toContain("Hasheminejad");
    const audit = auditCitations(stitched, references);
    expect(audit.missingInReferences).not.toContain("1");
    expect(audit.missingInReferences).not.toContain("10");
    expect(audit.unusedReferences.some((line) => /^27\./.test(line))).toBe(true);
    expect(formatUnused(audit.unusedReferences)).toEqual(expect.arrayContaining([27, 29]));
  });
});

function formatUnused(lines: string[]): number[] {
  return lines.map((line) => Number(line.split(".")[0])).filter((value) => Number.isFinite(value) && value > 0);
}