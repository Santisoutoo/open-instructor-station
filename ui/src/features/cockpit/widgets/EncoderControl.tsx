import { useEffect, useRef } from 'react';
import type { CockpitControlSpec } from '../../../api/models';

/** Delay before a held button starts auto-repeating. */
const HOLD_DELAY_MS = 450;
/** Repeat interval once auto-repeat has started. */
const REPEAT_MS = 150;

/**
 * One `±1` tap, or an auto-repeat while held, capped at `max_delta` per gesture (design
 * §7.1). The tap itself fires immediately on press-down rather than on release, so a
 * quick tap and the start of a long hold are the same code path — `stop()` on release
 * simply cuts a hold short. Pointer events only, deliberately: this panel lives on a
 * tablet next to the sim (CLAUDE.md).
 */
function useRepeatPress(onTick: () => void, maxTicks: number, disabled: boolean) {
  const timer = useRef<number | null>(null);
  const count = useRef(0);

  const stop = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  };

  // Never leave a repeat running past the widget's own lifetime.
  useEffect(() => stop, []);

  const fire = () => {
    if (count.current >= maxTicks) {
      stop();
      return;
    }
    count.current += 1;
    onTick();
  };

  const start = () => {
    if (disabled) {
      return;
    }
    count.current = 0;
    fire();
    timer.current = window.setTimeout(function repeat() {
      fire();
      if (count.current < maxTicks) {
        timer.current = window.setTimeout(repeat, REPEAT_MS);
      }
    }, HOLD_DELAY_MS);
  };

  return { onPointerDown: start, onPointerUp: stop, onPointerLeave: stop };
}

export interface EncoderControlProps {
  /** `step`/`max_delta` are required for `kind: "encoder"` (design §3.1). */
  spec: CockpitControlSpec;
  /** The confirmed read-back, or `null` when the binding has no `read` (unreadable). */
  value: number | null;
  pending: boolean;
  /** Signed click count — `±1` per tick, the design's "delta only" rule (D2). */
  onCommit: (delta: number) => void;
}

export function EncoderControl({ spec, value, pending, onCommit }: EncoderControlProps) {
  const maxTicks = spec.max_delta ?? 1;
  const unitSuffix = spec.unit === null || spec.unit === undefined ? '' : ` ${spec.unit}`;
  const current = value === null ? '—' : `${value}${unitSuffix}`;

  const dec = useRepeatPress(() => {
    onCommit(-1);
  }, maxTicks, pending);
  const inc = useRepeatPress(() => {
    onCommit(1);
  }, maxTicks, pending);

  return (
    <div className="control cockpit-encoder">
      <output className="control__value">{current}</output>
      <div className="control__row">
        <button type="button" className="control__button" disabled={pending} {...dec}>
          −
        </button>
        <button type="button" className="control__button" disabled={pending} {...inc}>
          +
        </button>
      </div>
    </div>
  );
}
