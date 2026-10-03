import { describe, expect, it } from "vitest";
import { parseTable } from "./tables";

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
});
