import { useEffect, useRef, useState } from 'react';

/**
 * A momentary control with no state to read back — `spec.readable` is always `false`
 * for `press` (design §3.1). The only feedback available is "the request left and the
 * server answered", so a brief "Sent" flash is the whole affordance; nothing here claims
 * the aircraft is now in any particular state. The flash fires whenever `pending` falls
 * regardless of outcome — a failed press still surfaces through the panel's error banner,
 * so this widget only needs to say "that request is no longer in flight".
 */
export interface PressControlProps {
  pending: boolean;
  onPress: () => void;
}

/** How long the post-success "Sent" flash stays up. */
const FLASH_MS = 1200;

export function PressControl({ pending, onPress }: PressControlProps) {
  const [flash, setFlash] = useState(false);
  const wasPending = useRef(false);

  // Flash exactly once, on the falling edge of `pending` — never on mount, never while
  // still in flight.
  useEffect(() => {
    if (pending) {
      wasPending.current = true;
      return undefined;
    }
    if (!wasPending.current) {
      return undefined;
    }
    wasPending.current = false;
    setFlash(true);
    const timer = window.setTimeout(() => {
      setFlash(false);
    }, FLASH_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [pending]);

  return (
    <button type="button" className="control__button" disabled={pending} onClick={onPress}>
      {pending ? 'Sending…' : flash ? 'Sent' : 'Press'}
    </button>
  );
}
