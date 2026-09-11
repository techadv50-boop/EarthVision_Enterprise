const NAMED: { test: RegExp; color: string }[] = [
  { test: /\bprss\b/i, color: '#facc15' },
  { test: /landsat/i, color: '#22c55e' },
];

const AUTO = [
  '#38bdf8',
  '#f472b6',
  '#a78bfa',
  '#fb7185',
  '#2dd4bf',
  '#f97316',
  '#e879f9',
  '#34d399',
  '#60a5fa',
  '#fbbf24',
];

export function colorForSatellite(name: string, used: Set<string>): string {
  for (const rule of NAMED) {
    if (rule.test.test(name) && !used.has(rule.color)) return rule.color;
  }
  return AUTO.find((c) => !used.has(c)) ?? AUTO[used.size % AUTO.length];
}
