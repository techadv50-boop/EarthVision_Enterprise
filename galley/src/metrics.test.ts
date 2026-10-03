import { describe, expect, it } from "vitest";
import {
  authorCitationName,
  buildCitation,
  endPageNumber,
  firstPageHeightInches,
  flowBody,
  numberAuthors,
  parseStartPage,
} from "./metrics";
import type { Author, BodyBlock } from "./types";

const authors: Author[] = [
  { id: "1", name: "Romaan khan", affiliation: "University of Agriculture Peshawar", corresponding: true, email: "romaan@aup.edu.pk" },
  { id: "2", name: "Tufail Ahmad Khan", affiliation: "Hazara University", corresponding: false, email: "" },
  { id: "3", name: "Muhammad Tahir", affiliation: "Hazara University", corresponding: false, email: "" },
  { id: "4", name: "Habib Un Nabi", affiliation: "University of Agriculture Peshawar", corresponding: false, email: "" },
];

describe("citation names", () => {
  it("puts the surname first and initials after, as in the sample", () => {
    expect(authorCitationName("Romaan khan")).toBe("Khan. R");
    expect(authorCitationName("Tufail Ahmad Khan")).toBe("Khan. T. A");
    expect(authorCitationName("Habib Un Nabi")).toBe("Nabi. H. U");
  });

  it("shares one affiliation number when the affiliation text matches", () => {
    const numbered = numberAuthors(authors);
    expect(numbered.affiliations).toEqual(["University of Agriculture Peshawar", "Hazara University"]);
    expect(numbered.authors.map((author) => author.affiliationNo)).toEqual([1, 2, 2, 1]);
  });

  it("builds the house citation and keeps the composer’s start page", () => {
    const line = buildCitation({
      authors,
      title: "Group-Aware Framework",
      abbreviation: "IJIST",
      volume: "7",
      issue: "4",
      startPage: 2705,
      endPage: 2717,
      published: "2025-11-08",
    });
    expect(line).toBe(
      "Citation | Khan. R, Khan. T. A, Tahir. M, Nabi. H. U, “Group-Aware Framework”, IJIST, Vol. 7 Issue. 4 pp 2705-2717, November 2025",
    );
  });
});

describe("page geometry", () => {
  const base = {
    title: "A short title",
    affiliationCount: 2,
    citation: "Citation | Khan. R, “Title”, IJIST, Vol. 7 Issue. 4 pp 2705-2706, November 2025",
    abstract: "Short abstract.",
    keywords: "Heart; Machine Learning",
    topIconCount: 2,
    partnerCount: 15,
    hasIssn: true,
  };

  it("grows the first page when the abstract or the icon rows grow", () => {
    const short = firstPageHeightInches(base);
    const long = firstPageHeightInches({
      ...base,
      abstract: "Accurate ".repeat(80),
    });
    const moreIcons = firstPageHeightInches({ ...base, partnerCount: 20 });
    expect(long).toBeGreaterThan(short);
    expect(moreIcons).toBeGreaterThan(short);
    expect(short).toBeGreaterThan(4);
  });

  it("numbers from the composer’s start, not from 1", () => {
    expect(parseStartPage("2705")).toBe(2705);
    expect(parseStartPage("1")).toBe(1);
    expect(parseStartPage("0")).toBeNull();
    expect(parseStartPage("")).toBeNull();
    expect(endPageNumber(2705, 12)).toBe(2717);
  });

  it("keeps a landscape table on its own page and returns to portrait", () => {
    const blocks: BodyBlock[] = [
      { id: "h", type: "heading", text: "Introduction:" },
      { id: "p", type: "paragraph", text: "One paragraph." },
      {
        id: "t",
        type: "table",
        caption: "Wide results",
        source: "A\tB",
        landscape: true,
        rows: [
          ["A", "B"],
          ["1", "2"],
        ],
      },
      { id: "c", type: "heading", text: "Conclusion:" },
      { id: "p2", type: "paragraph", text: "After the table." },
    ];
    const pages = flowBody(blocks);
    expect(pages.map((page) => page.kind)).toEqual(["portrait", "landscape", "portrait"]);
    expect(pages[1].kind === "landscape" && pages[1].block.id).toBe("t");
  });
});
