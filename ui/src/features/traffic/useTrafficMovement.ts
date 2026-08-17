import { useEffect } from 'react';
import { useAppDispatch } from '../../store';
import { advanceEntity } from './geo';
import { trafficApi } from './trafficApi';

/** One movement tick per second — smooth enough for a list, cheap enough for a tablet. */
export const MOVEMENT_TICK_MS = 1000;

/**
 * Keeps spawned traffic alive: every second, every active entity advances along its
 * track by `speed × dt`, written straight into the `getActiveTraffic` cache so every
 * subscriber re-renders with the new positions.
 *
 * Mounted by the panel; `enabled` is false while the gate is closed or nothing is
 * spawned, so an idle panel schedules no work. The interval clears on unmount.
 */
export function useTrafficMovement(enabled: boolean): void {
  const dispatch = useAppDispatch();

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const intervalId = setInterval(() => {
      dispatch(
        trafficApi.util.updateQueryData('getActiveTraffic', undefined, (draft) =>
          draft.map((entity) => advanceEntity(entity, MOVEMENT_TICK_MS / 1000)),
        ),
      );
    }, MOVEMENT_TICK_MS);
    return () => {
      clearInterval(intervalId);
    };
  }, [enabled, dispatch]);
}
