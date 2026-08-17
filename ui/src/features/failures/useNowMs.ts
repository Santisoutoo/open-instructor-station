/**
 * A once-a-second clock for the armed chips' delay countdowns.
 *
 * State is set only inside the interval callback (and the `useState` initialiser) —
 * never synchronously in the effect body, which the hooks lint rightly bans; same
 * shape as `scenarios/useElapsedSeconds.ts`. Disabled, it ticks nothing and the last
 * value goes stale, which is fine because nothing displays it then.
 */

import { useEffect, useState } from 'react';

export function useNowMs(enabled: boolean): number {
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const intervalId = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(intervalId);
    };
  }, [enabled]);

  return nowMs;
}
