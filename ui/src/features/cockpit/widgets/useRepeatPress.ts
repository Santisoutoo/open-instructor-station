import { useEffect, useRef } from 'react';

/** Delay before a held button starts auto-repeating. */
const HOLD_DELAY_MS = 450;
/** Repeat interval once auto-repeat has started. */
const REPEAT_MS = 150;

/**
 * One tick per tap, or an auto-repeat while held, capped at `maxTicks` per gesture
 * (design §7.1). The tap itself fires immediately on press-down rather than on release,
 * so a quick tap and the start of a long hold are the same code path — `stop()` on
 * release simply cuts a hold short. Pointer events only, deliberately: this panel lives
 * on a tablet next to the sim (CLAUDE.md).
 *
 * Extracted verbatim from the former `EncoderControl`. What `onTick` does is the
 * caller's business — `RotaryControl` edits the draft with it, never the wire.
 */
export function useRepeatPress(onTick: () => void, maxTicks: number, disabled: boolean) {
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
