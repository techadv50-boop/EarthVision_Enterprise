import { describe, expect, it } from "vitest";
import { atomsFromOcr, parseMath } from "./equations";

describe("equation OCR", () => {
  it("turns superscripts, subscripts, and ratios into editable parts", () => {
    const atoms = atomsFromOcr("y = x^2 + b_i + a/b");
    expect(atoms).toEqual([
      { kind: "text", value: "y" },
      { kind: "text", value: " " },
      { kind: "text", value: "=" },
      { kind: "text", value: " " },
      { kind: "text", value: "x" },
      { kind: "sup", value: "2" },
      { kind: "text", value: " " },
      { kind: "text", value: "+" },
      { kind: "text", value: " " },
      { kind: "text", value: "b" },
      { kind: "sub", value: "i" },
      { kind: "text", value: " " },
      { kind: "text", value: "+" },
      { kind: "text", value: " " },
      { kind: "frac", num: "a", den: "b" },
    ]);
  });

  it("keeps pasted symbols and builds superscripts, subscripts, and ratio lines", () => {
    expect(parseMath("α + β ≤ ∑ x^2")).toEqual([
      { kind: "text", value: "α + β ≤ ∑ x" },
      { kind: "sup", value: "2" },
    ]);
    expect(parseMath("\\frac{a+1}{b_i}")).toEqual([
      { kind: "frac", num: "a+1", den: "b_i" },
    ]);
    expect(parseMath("y = x² + bᵢ")).toEqual([
      { kind: "text", value: "y = x" },
      { kind: "sup", value: "2" },
      { kind: "text", value: " + b" },
      { kind: "sub", value: "i" },
    ]);
  });
});
