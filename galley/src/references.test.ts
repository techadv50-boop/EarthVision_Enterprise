import { describe, expect, it } from "vitest";
import { formatReference, parseAuthorList, parseReference } from "./references";

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
});
