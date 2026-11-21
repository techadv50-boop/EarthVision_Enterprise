export type QuestionMix = {
  fib: number;
  mcq: number;
  short: number;
  long: number;
  oral: number;
};

export type QuestionSeconds = QuestionMix;

const ORDER: (keyof QuestionMix)[] = ["mcq", "fib", "oral", "short", "long"];

export const ORAL_TOPIC_SECONDS = 180;

export const TIME_CHOICES: { minutes: number; label: string }[] = [
  { minutes: 15, label: "15 minutes" },
  { minutes: 30, label: "30 minutes" },
  { minutes: 45, label: "45 minutes" },
  { minutes: 60, label: "1 hour" },
  { minutes: 120, label: "2 hours" },
  { minutes: 180, label: "3 hours" },
];

export const MIX_LABELS: { key: keyof QuestionMix; singular: string; plural: string }[] = [
  { key: "fib", singular: "fill in the blank", plural: "fill in the blanks" },
  { key: "mcq", singular: "multiple-choice question", plural: "multiple-choice questions" },
  { key: "short", singular: "short question", plural: "short questions" },
  { key: "long", singular: "long question", plural: "long questions" },
  { key: "oral", singular: "oral topic", plural: "oral topics" },
];

/** How many equal items fit in the chosen period, never more than the notes provide. */
export function countWithinTime(minutes: number, available: number, secondsEach: number): number {
  if (minutes <= 0 || available <= 0 || secondsEach <= 0) return 0;
  return Math.min(available, Math.floor((minutes * 60) / secondsEach));
}

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
