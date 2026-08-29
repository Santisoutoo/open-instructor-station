/**
 * Wind head/cross/tail decomposition for a runway of a given true course.
 *
 * Ported verbatim from the v3 source's formula (design doc, "Derived logic" — wind
 * components). `head` is signed (positive = headwind, negative = tailwind); `tail` is the
 * unsigned tailwind magnitude, `0` whenever there is a headwind component. Head and tail are
 * mutually exclusive by construction — never read both as non-zero at once.
 */

export interface WindComponents {
  /** Positive = headwind, negative = tailwind. */
  readonly head: number;
  readonly cross: number;
  /** Unsigned tailwind magnitude; `0` whenever `head >= 0`. */
  readonly tail: number;
}

export function windComponents(
  windDeg: number,
  windKt: number,
  courseDeg: number,
): WindComponents {
  const relative = (((windDeg - courseDeg + 540) % 360) - 180) * (Math.PI / 180);
  const head = Math.round(windKt * Math.cos(relative));
  const cross = Math.round(Math.abs(windKt * Math.sin(relative)));
  const tail = head < 0 ? -head : 0;
  return { head, cross, tail };
}

/** The per-runway-tab wind string: `"7 kt head"` (dim) or `"5 kt tail"` (caution). */
export function runwayWind(
  windDeg: number,
  windKt: number,
  courseDeg: number,
): { text: string; caution: boolean } {
  const { head, tail } = windComponents(windDeg, windKt, courseDeg);
  return tail > 0
    ? { text: `${String(tail)} kt tail`, caution: true }
    : { text: `${String(head)} kt head`, caution: false };
}

/** The Approach tab's compound wind text: `"11 kt tail · 4 kt cross"`. */
export function approachWindText(windDeg: number, windKt: number, courseDeg: number): string {
  const { head, tail, cross } = windComponents(windDeg, windKt, courseDeg);
  const longitudinal = tail > 0 ? `${String(tail)} kt tail` : `${String(head)} kt head`;
  return `${longitudinal} · ${String(cross)} kt cross`;
}
