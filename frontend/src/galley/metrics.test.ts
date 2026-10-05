import { describe, expect, it } from "vitest";
import {
  authorCitationName,
  buildCitation,
  clampDateToCurrentEra,
  currentYear,
  displayFigureCaption,
  displayTableCaption,
  endPageNumber,
  firstPageHeightInches,
  flowBody,
  formatMonthYear,
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

  it("caps a run of fake initials and keeps a normal given-name surname", () => {
    expect(authorCitationName("Abid. M. F. M. M. S. F. M. M. A")).toBe("Abid. M. F. M");
    expect(authorCitationName("Muhammad Farooq Abid")).toBe("Abid. M. F");
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
      journal: "International Journal of Innovations in Science & Technology",
      volume: "7",
      issue: "4",
      startPage: 2705,
      endPage: 2717,
      published: "2025-11-08",
      doi: "10.33411/ijist/example",
    });
    expect(line).toBe(
      "Khan. R, Khan. T. A, Tahir. M, Nabi. H. U, “Group-Aware Framework”, International Journal of Innovations in Science & Technology, Vol. 7, Issue 4, pp 2705-2717, November 2025, https://doi.org/10.33411/ijist/example",
    );
  });

  it("treats impossible years such as 4454 as the current year", () => {
    expect(clampDateToCurrentEra("4454-04-01")).toBe(`${currentYear()}-04-01`);
    expect(formatMonthYear("4454-04-01")).toBe(`April ${currentYear()}`);
    const line = buildCitation({
      authors: [{ id: "1", name: "Romaan khan", affiliation: "", corresponding: false, email: "" }],
      title: "Group-Aware Framework",
      journal: "IJIST",
      volume: "8",
      issue: "2",
      startPage: 12,
      endPage: 20,
      published: "4454-04-01",
      doi: "10.1/example",
    });
    expect(line).toContain(`April ${currentYear()}`);
    expect(line).not.toContain("4454");
    expect(line).toContain("Vol. 8");
    expect(line).toContain("Issue 2");
    expect(line).toContain("pp 12-20");
  });

  it("does not print Table twice when the pasted caption already has a number", () => {
    expect(displayTableCaption("Table 5 Performance Comparison of This Study with Existing Techniques", 3)).toBe(
      "Table 3. Performance Comparison of This Study with Existing Techniques",
    );
    expect(displayTableCaption("Table 3. Table 5 Results", 3)).toBe("Table 3. Results");
  });

  it("does not print Figure twice when the pasted caption already has a number", () => {
    expect(displayFigureCaption("Figure 3. Percentage of Quality Score for Quality Assessment Question No.1", 3)).toBe(
      "Figure 3. Percentage of Quality Score for Quality Assessment Question No.1",
    );
    expect(displayFigureCaption("Figure 3. Figure 3. Quality score", 3)).toBe("Figure 3. Quality score");
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

  it("moves a heading that would sit at the page foot onto the next page and stretches the figure", () => {
    const figure: BodyBlock = {
      id: "fig",
      type: "figure",
      dataUrl: "",
      widthPx: 400,
      heightPx: 220,
      caption: "Results",
    };
    const filler: BodyBlock[] = Array.from({ length: 44 }, (_, index) => ({
      id: `p${index}`,
      type: "paragraph",
      text: "Short line.",
    }));
    const pages = flowBody([
      ...filler,
      figure,
      { id: "h", type: "heading", text: "Discussion:" },
      { id: "after", type: "paragraph", text: "The heading must travel with this paragraph." },
    ]);
    const portrait = pages.filter((page) => page.kind === "portrait");
    expect(portrait.length).toBeGreaterThan(1);
    const lastWithFigure = portrait.find((page) => page.kind === "portrait" && page.blocks.some((block) => block.id === "fig"));
    const headingPage = portrait.find((page) => page.kind === "portrait" && page.blocks.some((block) => block.id === "h"));
    expect(lastWithFigure && headingPage && lastWithFigure !== headingPage).toBe(true);
    const flowed = lastWithFigure && lastWithFigure.kind === "portrait"
      ? lastWithFigure.blocks.find((block) => block.id === "fig")
      : undefined;
    expect(flowed && flowed.type === "figure" && flowed.heightPx > 220).toBe(true);
  });

  it("shrinks a tall figure to fill leftover space instead of leaving a gap", () => {
    const filler: BodyBlock[] = Array.from({ length: 40 }, (_, index) => ({
      id: `p${index}`,
      type: "paragraph",
      text: "Short line.",
    }));
    const figure: BodyBlock = {
      id: "big",
      type: "figure",
      dataUrl: "",
      widthPx: 800,
      heightPx: 900,
      caption: "Quality score",
    };
    const pages = flowBody([...filler, figure]);
    const portrait = pages.filter((page) => page.kind === "portrait");
    const withFigure = portrait.find((page) => page.kind === "portrait" && page.blocks.some((block) => block.id === "big"));
    expect(withFigure && withFigure.kind === "portrait" && withFigure.blocks.some((block) => block.type === "paragraph")).toBe(true);
    const flowed = withFigure && withFigure.kind === "portrait" ? withFigure.blocks.find((block) => block.id === "big") : undefined;
    expect(flowed && flowed.type === "figure" && flowed.heightPx < 900).toBe(true);
    expect(flowed && flowed.type === "figure" && flowed.heightPx >= 160).toBe(true);
  });

  it("moves the paragraph before a figure when shrinking it would make the figure too small", () => {
    const filler: BodyBlock[] = Array.from({ length: 42 }, (_, index) => ({
      id: `p${index}`,
      type: "paragraph",
      text: "Short line.",
    }));
    const before: BodyBlock = { id: "before", type: "paragraph", text: "The sentence immediately before the figure." };
    const figure: BodyBlock = {
      id: "tiny-room",
      type: "figure",
      dataUrl: "",
      widthPx: 800,
      heightPx: 700,
      caption: "Responses",
    };
    const pages = flowBody([...filler, before, figure]);
    const portrait = pages.filter((page) => page.kind === "portrait");
    const figurePage = portrait.find((page) => page.kind === "portrait" && page.blocks.some((block) => block.id === "tiny-room"));
    expect(figurePage && figurePage.kind === "portrait" && figurePage.blocks.some((block) => block.id === "before")).toBe(true);
    expect(figurePage && figurePage.kind === "portrait" && figurePage.blocks.some((block) => block.id === "tiny-room")).toBe(true);
  });
});
