/**
 * Pure maths for the rotary widgets (issue #253, design §2/§3) — no React, no I/O.
 *
 * A dial edits a **draft** (the number-field text) and an encoder accumulates **clicks**;
 * neither reaches the wire until an explicit commit. Everything here answers "what would
 * that commit send" or "what does one wheel notch / key / `±` tap do to the draft", so
 * `RotaryControl`, the schematic slots and `useRotaryDraft` all agree on the numbers.
 *
 * Every result that can end up on the wire either goes through {@link roundToStep} or
 * is a detent value straight from the layout table, so `0.1 + 0.2` junk never leaves
 * the client — the server compares the read-back against `readback_tolerance`, and a
 * `0.30000000000000004` written for `0.3` is a needless mismatch.
 */

import type { CockpitControlSpec } from '../../../api/models';
import type { Detent, LayoutSlot, ValueFormat } from '../layouts';

/** The transient edit state of one rotary control. `controlId === null` is "no draft". */
export interface RotaryDraft {
  readonly controlId: string | null;
  readonly kind: 'dial' | 'encoder' | null;
  /** Dial: the number-field text. Empty means "nothing typed yet". */
  readonly text: string;
  /** Encoder: signed accumulated clicks, saturating at `±max_delta`. */
  readonly clicks: number;
}

export const EMPTY_ROTARY_DRAFT: RotaryDraft = {
  controlId: null,
  kind: null,
  text: '',
  clicks: 0,
};

/**
 * What `useRotaryDraft` hands out. Every mutation carries its `spec` so a wheel notch on
 * an unfocused knob starts that knob's draft and lands on it in the same event.
 */
export interface RotaryDraftHandle {
  readonly draft: RotaryDraft;
  /** True when the draft belongs to `controlId`. */
  isFor(controlId: string): boolean;
  /** Dial only: replace the number-field text. A different control_id starts a fresh draft. */
  setText(spec: CockpitControlSpec, text: string): void;
  /**
   * Wheel / keys / `±`: dial → base (valid draft, else `confirmed`, else min) nudged via
   * {@link nudgeDial}; encoder → {@link nudgeEncoder} saturating at `spec.max_delta`. A
   * different control_id starts a fresh draft first.
   */
  nudge(
    spec: CockpitControlSpec,
    slot: LayoutSlot | undefined,
    confirmed: number | null,
    sign: 1 | -1,
    count?: number,
  ): void;
  /** Discard (Escape). */
  reset(): void;
  /**
   * What a commit would send: `{ value }` for a valid dial draft, `{ delta: clicks }` for
   * an encoder with clicks ≠ 0, `null` when there is nothing valid to commit.
   */
  body(
    spec: CockpitControlSpec,
    slot: LayoutSlot | undefined,
  ): { value: number } | { delta: number } | null;
}

/** Beyond this the float itself has no more digits to give. */
const MAX_DECIMALS = 15;
/** `0.0007 × 10⁴` is `7.000000000000001` — the integer test needs slack. */
const INTEGER_SLACK = 1e-9;

/** Locale pinned so the readout is identical on the tablet, the desktop and in CI. */
const PLAIN_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 3 });

/**
 * Decimal places a step needs to be written exactly: `0.125 → 3`, `100 → 0`,
 * `0.0007 → 4`. Computed by scaling, not by reading `String(step)` — `1e-7` has no dot.
 */
export function stepDecimals(step: number): number {
  if (!Number.isFinite(step) || step === 0) {
    return 0;
  }
  for (let decimals = 0; decimals < MAX_DECIMALS; decimals += 1) {
    const scaled = step * 10 ** decimals;
    if (Math.abs(scaled - Math.round(scaled)) < INTEGER_SLACK) {
      return decimals;
    }
  }
  return MAX_DECIMALS;
}

/**
 * The nearest multiple of `step` from `origin`, written with exactly the decimals the
 * step needs. A non-positive or non-finite step leaves the value alone.
 */
export function roundToStep(value: number, step: number, origin = 0): number {
  if (!Number.isFinite(step) || step <= 0) {
    return value;
  }
  const snapped = origin + Math.round((value - origin) / step) * step;
  return Number(snapped.toFixed(stepDecimals(step)));
}

/**
 * Wrap into `[min, max)` when `wrap` is set and both bounds are finite (a heading:
 * `359 + 1 → 0`); clamp into `[min, max]` otherwise.
 */
export function clampOrWrap(
  value: number,
  min: number,
  max: number,
  wrap: boolean,
): number {
  if (wrap && Number.isFinite(min) && Number.isFinite(max) && max > min) {
    const span = max - min;
    return ((((value - min) % span) + span) % span) + min;
  }
  return Math.min(max, Math.max(min, value));
}

function ascending(detents: readonly Detent[]): readonly Detent[] {
  return [...detents].sort((a, b) => a.value - b.value);
}

/** Index of the detent nearest `value` in an ascending list; a tie goes to the lower one. */
function nearestDetentIndex(sorted: readonly Detent[], value: number): number {
  let best = 0;
  let bestDistance = Infinity;
  sorted.forEach((detent, index) => {
    const distance = Math.abs(detent.value - value);
    if (distance < bestDistance) {
      best = index;
      bestDistance = distance;
    }
  });
  return best;
}

/** The value of the detent nearest `value` (ties → the lower one); `value` itself if none. */
export function snapToDetent(value: number, detents: readonly Detent[]): number {
  if (detents.length === 0) {
    return value;
  }
  const sorted = ascending(detents);
  return sorted[nearestDetentIndex(sorted, value)]?.value ?? value;
}

function dialRange(spec: CockpitControlSpec): { min: number; max: number; step: number } {
  return {
    min: spec.min_value ?? -Infinity,
    max: spec.max_value ?? Infinity,
    step: spec.step ?? 1,
  };
}

/**
 * One nudge of a dial draft: `count` detents in `sign` direction from the detent nearest
 * `base` (saturating at the ends) when the slot has detents; otherwise `base ± count ×
 * step`, wrapped or clamped into the spec's range and written on the step grid.
 */
export function nudgeDial(
  spec: CockpitControlSpec,
  slot: LayoutSlot | undefined,
  base: number,
  sign: 1 | -1,
  count = 1,
): number {
  const { min, max, step } = dialRange(spec);
  const detents = slot?.detents;
  if (detents !== undefined && detents.length > 0) {
    const sorted = ascending(detents);
    const from = nearestDetentIndex(sorted, base);
    const to = Math.min(sorted.length - 1, Math.max(0, from + sign * count));
    return sorted[to]?.value ?? base;
  }
  const wrap = slot?.wrap ?? false;
  const moved = clampOrWrap(base + sign * count * step, min, max, wrap);
  // Rounding can land exactly on `max`, which a wrapped range excludes — settle it again.
  return clampOrWrap(roundToStep(moved, step), min, max, wrap);
}

/**
 * The value a commit of the number-field `text` would send, or `null` when the text is
 * empty or not a finite number. Wrapped/clamped into range, then snapped to the slot's
 * detents when it has them (a detent value is table data and goes out verbatim) or
 * written on the step grid otherwise.
 */
export function dialDraftValue(
  spec: CockpitControlSpec,
  slot: LayoutSlot | undefined,
  text: string,
): number | null {
  const trimmed = text.trim();
  if (trimmed === '') {
    return null;
  }
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  const { min, max, step } = dialRange(spec);
  const wrap = slot?.wrap ?? false;
  const inRange = clampOrWrap(parsed, min, max, wrap);
  const detents = slot?.detents;
  if (detents !== undefined && detents.length > 0) {
    return snapToDetent(inRange, detents);
  }
  return clampOrWrap(roundToStep(inRange, step), min, max, wrap);
}

/** `clicks ± count`, saturating at `±maxDelta` — the per-gesture cap of design §7.1. */
export function nudgeEncoder(
  clicks: number,
  sign: 1 | -1,
  count: number,
  maxDelta: number,
): number {
  return Math.min(maxDelta, Math.max(-maxDelta, clicks + sign * count));
}

/**
 * Where the encoder's value would land after `clicks` (`confirmed + clicks × step`,
 * written on the step's decimals), or `null` while nothing has been read back — it is
 * a prediction for the readout, never a value that is written.
 */
export function predictedEncoderValue(
  confirmed: number | null,
  clicks: number,
  step: number,
): number | null {
  if (confirmed === null) {
    return null;
  }
  return Number((confirmed + clicks * step).toFixed(stepDecimals(step)));
}

/**
 * Readout text. `khz` values arrive as MHz×100 (`11800 → "118.00 MHz"`), `octal` is a
 * four-digit squawk (`512 → "0512"`), `plain` is the number with its unit.
 */
export function formatValue(
  value: number | null,
  unit: CockpitControlSpec['unit'],
  format?: ValueFormat,
): string {
  if (value === null) {
    return '—';
  }
  switch (format) {
    case 'khz':
      return `${(value / 100).toFixed(2)} MHz`;
    case 'octal':
      return String(value).padStart(4, '0');
    case 'plain':
    case undefined:
      return `${PLAIN_FORMAT.format(value)}${unit ? ` ${unit}` : ''}`;
  }
}

/** Pixels one `deltaMode: 1` (line) wheel unit stands for — Chrome's own line height. */
const LINE_PX = 16;
/** Accumulated wheel pixels per notch. */
const DEFAULT_NOTCH_PX = 50;

/**
 * Turn one `wheel` event into notches. Scrolling **up** (`deltaY < 0`) is clockwise and
 * yields **positive** notches. Pixels accumulate into `carry` (kept in `deltaY`'s own
 * sign convention); every full `threshold` emits a notch and the remainder carries over.
 * A change of direction throws the carry away first, so a jittery trackpad reversal
 * never pays out a notch it did not earn.
 */
export function wheelNotches(
  carry: number,
  deltaY: number,
  deltaMode: number,
  threshold = DEFAULT_NOTCH_PX,
): { notches: number; carry: number } {
  const px =
    deltaMode === 1 ? deltaY * LINE_PX : deltaMode === 2 ? deltaY * threshold : deltaY;
  if (px === 0) {
    return { notches: 0, carry };
  }
  const kept = carry !== 0 && Math.sign(px) !== Math.sign(carry) ? 0 : carry;
  const total = kept + px;
  const magnitude = Math.floor(Math.abs(total) / threshold);
  const direction = Math.sign(total);
  return {
    // `|| 0` normalises `-0`, which `Object.is` (and so `toBe`) would tell apart.
    notches: -direction * magnitude || 0,
    carry: total - direction * magnitude * threshold || 0,
  };
}
