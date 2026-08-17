/**
 * Elapsed-time formatting for the active scenario bar. Pure on purpose: `now` is a
 * parameter, never read inside, so every path is testable without a clock.
 */

/** Whole seconds between two epoch-ms instants, clamped at zero. */
export function elapsedSeconds(startedAt: number, now: number): number {
  return Math.max(0, Math.floor((now - startedAt) / 1000));
}

/** `mm:ss`, zero-padded: 65 s → `01:05`. Minutes keep growing past an hour. */
export function formatSeconds(totalSeconds: number): string {
  const clamped = Math.max(0, Math.floor(totalSeconds));
  const minutes = String(Math.floor(clamped / 60)).padStart(2, '0');
  const seconds = String(clamped % 60).padStart(2, '0');
  return `${minutes}:${seconds}`;
}

/** Elapsed time between `startedAt` and `now` as `mm:ss`. */
export function formatElapsed(startedAt: number, now: number): string {
  return formatSeconds(elapsedSeconds(startedAt, now));
}
