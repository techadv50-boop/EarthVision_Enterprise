import { describe, expect, it } from "vitest";
import { parseTable, columnWidths, cleanTableCell } from "./tables";

describe("pasted tables", () => {
  it("reads a copied spreadsheet as rows and columns", () => {
    const rows = parseTable("Model\tAUC\nCatBoost\t0.91\nSVM\t0.84");
    expect(rows).toEqual([
      ["Model", "AUC"],
      ["CatBoost", "0.91"],
      ["SVM", "0.84"],
    ]);
  });

  it("reads an HTML table from a Word or web paste", () => {
    const rows = parseTable("<table><tr><td>Age</td><td>Years</td></tr><tr><td>Sex</td><td>M/F</td></tr></table>");
    expect(rows).toEqual([
      ["Age", "Years"],
      ["Sex", "M/F"],
    ]);
  });

  it("gives a year column only as much width as the year needs", () => {
    const widths = columnWidths([
      ["Name of the dataset", "Year", "Records"],
      ["Long climate observations from several stations", "2016", "12"],
    ]);
    expect(widths[1]).toBeLessThan(widths[0]);
    expect(widths.reduce((sum, value) => sum + value, 0)).toBe(100);
  });

  it("strips a Mendeley ADDIN dump and keeps Year wider than a single letter", () => {
    const html = `<table><tr><td>Author(s)</td><td>Year</td><td>Method</td></tr><tr><td>Stamatatos et al. ADDIN CSL_CITATION {&quot;citationItems&quot;:[{&quot;id&quot;:&quot;ITEM-1&quot;,&quot;formattedCitation&quot;:&quot;Stamatatos et al., 2009&quot;}]}</td><td>2009</td><td>n-gram</td></tr></table>`;
    const rows = parseTable(html);
    expect(rows[1][0]).toBe("Stamatatos et al.");
    expect(rows[1][1]).toBe("2009");
    expect(rows[1][0]).not.toMatch(/citationItems|ADDIN/);
    const widths = columnWidths(rows);
    expect(widths[1]).toBeGreaterThanOrEqual(10);
    expect(widths[0]).toBeGreaterThan(widths[1]);
    expect(
      cleanTableCell(
        'Stamatatos et al. ADDIN CSL_CITATION {"citationItems":[{"formattedCitation":"Stamatatos 2009"}]}',
      ),
    ).toBe("Stamatatos et al.");
  });
});
