export function remainingMs(origin: number, now: number, durationMs: number): number {
  return Math.max(0, durationMs - (now - origin));
}

export function originForRemaining(now: number, durationMs: number, remaining: number): number {
  const clamped = Math.max(0, Math.min(durationMs, remaining));
  return now - (durationMs - clamped);
}
