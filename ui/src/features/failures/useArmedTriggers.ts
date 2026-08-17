/**
 * The armed-trigger evaluator: while anything is armed, check every trigger against
 * the latest telemetry frame once a second and promote what fires into the active
 * list, written straight into the `getFailureBoard` cache so every subscriber
 * re-renders — the same panel-mounted pattern as `traffic/useTrafficMovement.ts`.
 *
 * At backend integration the server's trigger evaluator does this against the real
 * state stream (feature-spec §2) and this hook is replaced by the WebSocket reporting
 * promotions.
 */

import { useEffect } from 'react';
import { useAppDispatch, useAppStore } from '../../store';
import { failuresApi } from './failuresApi';
import { triggerFired } from './triggers';

/** One evaluation per second — triggers are human-scale conditions, not autopilots. */
export const TRIGGER_TICK_MS = 1000;

/**
 * Mounted by the panel; `enabled` is false while the gate is closed or nothing is
 * armed, so an idle panel schedules no work. The interval clears on unmount. The tick
 * reads board and telemetry from the store directly, so a 4 Hz telemetry feed never
 * restarts the interval.
 */
export function useArmedTriggers(enabled: boolean): void {
  const dispatch = useAppDispatch();
  const store = useAppStore();

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const intervalId = window.setInterval(() => {
      const state = store.getState();
      const board = failuresApi.endpoints.getFailureBoard.select(undefined)(state).data;
      if (board === undefined || board.armed.length === 0) {
        return;
      }
      const frame = state.telemetry.latest;
      const nowMs = Date.now();
      const fired = board.armed.filter((armed) => triggerFired(armed, frame, nowMs));
      if (fired.length === 0) {
        return;
      }
      const firedIds = new Set(fired.map((armed) => armed.failureId));
      dispatch(
        failuresApi.util.updateQueryData('getFailureBoard', undefined, (draft) => {
          draft.armed = draft.armed.filter((armed) => !firedIds.has(armed.failureId));
          for (const hit of fired) {
            if (!draft.active.some((active) => active.failureId === hit.failureId)) {
              draft.active.push({ failureId: hit.failureId, activatedAt: nowMs });
            }
          }
        }),
      );
    }, TRIGGER_TICK_MS);
    return () => {
      window.clearInterval(intervalId);
    };
  }, [enabled, dispatch, store]);
}
