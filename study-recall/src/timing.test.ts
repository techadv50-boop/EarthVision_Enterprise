import { describe, expect, it } from "vitest";
import { originForRemaining, remainingMs } from "./timing";

describe("examination timer", () => {
  it("counts down from a monotonic origin and does not go below zero", () => {
    expect(remainingMs(1_000, 1_400, 1_000)).toBe(600);
    expect(remainingMs(1_000, 3_000, 1_000)).toBe(0);
  });

  it("restarts a recovered question from the remaining time", () => {
    const now = 10_000;
    const origin = originForRemaining(now, 45_000, 12_000);
    expect(remainingMs(origin, now, 45_000)).toBe(12_000);
    expect(remainingMs(origin, now + 12_000, 45_000)).toBe(0);
  });
});
