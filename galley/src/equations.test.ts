import { describe, expect, it } from "vitest";
import { atomsFromOcr } from "./equations";

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
});
