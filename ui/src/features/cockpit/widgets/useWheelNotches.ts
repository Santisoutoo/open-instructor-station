/**
 * Mouse-wheel notches for a rotary widget (issue #253, design §3).
 *
 * A **native** `wheel` listener registered `{ passive: false }`: React's root listener
 * is passive, so a `preventDefault()` in an `onWheel` prop is ignored and the page
 * scrolls under the knob. Every event while enabled is prevented — a knob under the
 * pointer owns the wheel outright. Pixels accumulate in a ref through
 * {@link wheelNotches}; a full notch calls `onNotch(sign, count)` with scroll-up as `+1`
 * (clockwise = increase). The wheel edits a draft only; nothing here writes.
 */

import { useEffect, useRef, type RefObject } from 'react';
import { wheelNotches } from './rotary';

export function useWheelNotches(
  ref: RefObject<HTMLElement | null>,
  onNotch: (sign: 1 | -1, count: number) => void,
  enabled = true,
): void {
  // The latest callback, read at event time, so the listener is attached once per
  // `[ref, enabled]` rather than on every render.
  const onNotchRef = useRef(onNotch);
  useEffect(() => {
    onNotchRef.current = onNotch;
  });

  const carry = useRef(0);

  useEffect(() => {
    const element = ref.current;
    if (!enabled || element === null) {
      return undefined;
    }
    carry.current = 0;
    const listener = (event: WheelEvent) => {
      event.preventDefault();
      const result = wheelNotches(carry.current, event.deltaY, event.deltaMode);
      carry.current = result.carry;
      if (result.notches !== 0) {
        onNotchRef.current(result.notches > 0 ? 1 : -1, Math.abs(result.notches));
      }
    };
    element.addEventListener('wheel', listener, { passive: false });
    return () => {
      element.removeEventListener('wheel', listener);
      carry.current = 0;
    };
  }, [ref, enabled]);
}
