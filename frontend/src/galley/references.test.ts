import { describe, expect, it } from "vitest";
import { formatReference, parseAuthorList, parseReference, segregateReferences } from "./references";

const sample =
  '[29] C. Zhang, J. Wang, and Y. Shi, "A CNN-transformer hybrid network for image super-resolution," IEEE Transactions on Image Processing, vol. 29, no. 4, pp. 12-20, 2026, doi: 10.1109/TIP.2026.1';

describe("reference parsing", () => {
  it("splits a journal reference into the Mendeley fields", () => {
    const item = parseReference(sample);
    expect(item.kind).toBe("journal");
    expect(item.title).toBe("A CNN-transformer hybrid network for image super-resolution");
    expect(item.container).toContain("IEEE Transactions on Image Processing");
    expect(item.volume).toBe("29");
    expect(item.issue).toBe("4");
    expect(item.pages).toBe("12-20");
    expect(item.year).toBe("2026");
    expect(item.doi).toBe("10.1109/TIP.2026.1");
    expect(parseAuthorList(item.authors).map((author) => author.family)).toEqual(["Zhang", "Wang", "Shi"]);
  });

  it("recognises a book and a conference paper", () => {
    expect(parseReference("A. Author, Data Structures, Oxford University Press, 2024.").kind).toBe("book");
    expect(
      parseReference('B. Author, "Crop models," in Proceedings of the Agriculture Conference, 2023, pp. 1-8.').kind,
    ).toBe("conference");
  });

  it("rewrites the same fields when the style changes", () => {
    const item = parseReference(sample);
    const ieee = formatReference(item, "ieee", 1);
    const apa = formatReference(item, "apa", 1);
    expect(ieee.startsWith("[1] C. Zhang")).toBe(true);
    expect(ieee).toContain("vol. 29, no. 4");
    expect(apa.startsWith("Zhang, C.")).toBe(true);
    expect(apa).toContain("(2026)");
    expect(apa).toContain("29(4)");
    expect(apa).not.toContain("[1]");
    expect(formatReference(item, "vancouver", 2).startsWith("2. Zhang C")).toBe(true);
  });

  it("segregates a pasted list into author, title, journal, month, issue, volume, pages, URL, and DOI", () => {
    const items = segregateReferences(`[1] A. Author, "Title one," Journal of Testing, vol. 2, no. 3, pp. 4-5, November 2024, doi: 10.1000/one https://example.com/one

[2] B. Author, "Title two," Other Journal, vol. 8, no. 1, pp. 9-10, 2023.`);
    expect(items).toHaveLength(2);
    expect(items[0].authors).toContain("Author");
    expect(items[0].title).toBe("Title one");
    expect(items[0].container).toContain("Journal of Testing");
    expect(items[0].volume).toBe("2");
    expect(items[0].issue).toBe("3");
    expect(items[0].pages).toBe("4-5");
    expect(items[0].month).toBe("November");
    expect(items[0].year).toBe("2024");
    expect(items[0].doi).toBe("10.1000/one");
    expect(items[0].url).toBe("https://example.com/one");
    expect(formatReference(items[0], "apa", 1)).toContain("November 2024");
    expect(formatReference(items[0], "apa", 1)).toContain("https://example.com/one");
    expect(formatReference(items[0], "ieee", 1)).toContain("[1]");
    expect(formatReference(items[0], "ieee", 1)).not.toContain("(November 2024)");
  });
});
