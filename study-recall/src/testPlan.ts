export type QuestionMix = {
  fib: number;
  mcq: number;
  short: number;
  long: number;
  oral: number;
};

export type QuestionSeconds = QuestionMix;

const ORDER: (keyof QuestionMix)[] = ["mcq", "fib", "oral", "short", "long"];

export function estimateSeconds(mix: QuestionMix, seconds: QuestionSeconds): number {
  return ORDER.reduce((total, key) => total + mix[key] * seconds[key], 0);
}

/** Fills a mix that stays inside the time the student has, using every type the notes can support. */
export function fitMix(targetSeconds: number, caps: QuestionMix, seconds: QuestionSeconds): QuestionMix {
  const mix: QuestionMix = { fib: 0, mcq: 0, short: 0, long: 0, oral: 0 };
  let added = true;
  while (added) {
    added = false;
    for (const key of ORDER) {
      if (mix[key] >= caps[key] || seconds[key] <= 0) continue;
      const next = { ...mix, [key]: mix[key] + 1 };
      if (estimateSeconds(next, seconds) > targetSeconds) continue;
      mix[key] += 1;
      added = true;
    }
  }
  if (estimateSeconds(mix, seconds) === 0) {
    const shortest = ORDER.filter((key) => caps[key] > 0).sort((a, b) => seconds[a] - seconds[b])[0];
    if (shortest) mix[shortest] = 1;
  }
  return mix;
}

export function useAll(caps: QuestionMix): QuestionMix {
  return { ...caps };
}
