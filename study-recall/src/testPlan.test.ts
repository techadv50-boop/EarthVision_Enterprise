import { describe, expect, it } from "vitest";
import { estimateSeconds, fitMix } from "./testPlan";

const seconds = { mcq: 45, fib: 60, oral: 180, short: 240, long: 600 };

describe("student test plan", () => {
  it("keeps a 30 minute mix inside the time and uses more than one type", () => {
    const mix = fitMix(30 * 60, { fib: 20, mcq: 20, short: 6, long: 2, oral: 10 }, seconds);
    expect(estimateSeconds(mix, seconds)).toBeLessThanOrEqual(30 * 60);
    expect(mix.mcq).toBeGreaterThan(0);
    expect(mix.fib).toBeGreaterThan(0);
    expect(mix.oral).toBeGreaterThan(0);
    expect(mix.long).toBe(1);
    const shortSession = fitMix(15 * 60, { fib: 20, mcq: 20, short: 6, long: 2, oral: 10 }, seconds);
    expect(estimateSeconds(shortSession, seconds)).toBeLessThanOrEqual(15 * 60);
    expect(shortSession.long).toBe(0);
    expect(shortSession.mcq).toBeGreaterThan(0);
  });

  it("does not ask for more questions than the notes can support", () => {
    const mix = fitMix(60 * 60, { fib: 1, mcq: 0, short: 0, long: 0, oral: 2 }, seconds);
    expect(mix).toEqual({ fib: 1, mcq: 0, short: 0, long: 0, oral: 2 });
  });
});
