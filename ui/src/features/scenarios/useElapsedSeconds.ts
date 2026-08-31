/**
 * Whole seconds elapsed since `startedAt`, ticking once a second.
 *
 * State is set only inside the interval callback (and the `useState` initialiser) —
 * never synchronously in the effect body, which the hooks lint rightly bans. The first
 * rendered value therefore comes from the initialiser, not from an effect-time set.
 */

import { useEffect, useState } from 'react';
import { elapsedSeconds } from './format';

export function useElapsedSeconds(startedAt: number): number {
  const [seconds, setSeconds] = useState(() => elapsedSeconds(startedAt, Date.now()));

  useEffect(() => {
    const id = window.setInterval(() => {
      setSeconds(elapsedSeconds(startedAt, Date.now()));
    }, 1000);
    return () => {
      window.clearInterval(id);
    };
  }, [startedAt]);

  return seconds;
}
