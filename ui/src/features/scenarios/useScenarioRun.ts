/**
 * The mock run engine: while a run is live, tick one step per interval.
 *
 * This is a visual progression only — it dispatches into the scenarios slice and
 * nowhere else. At backend integration the server executes the plan and this hook is
 * replaced by the WebSocket reporting real step completion.
 */

import { useEffect } from 'react';
import { useAppDispatch, useAppSelector } from '../../store';
import { runStepCompleted } from './scenariosSlice';

export const RUN_STEP_INTERVAL_MS = 1200;

export function useScenarioRun(): void {
  const dispatch = useAppDispatch();
  const runState = useAppSelector((state) => state.scenarios.runState);

  // Collapsed to a boolean so completing a step (a new runState object) does not
  // restart the interval — the cadence stays steady across the whole run.
  const running =
    runState !== null && !runState.stopped && runState.steps.some((step) => !step.done);

  useEffect(() => {
    if (!running) {
      return;
    }
    const id = window.setInterval(() => {
      dispatch(runStepCompleted());
    }, RUN_STEP_INTERVAL_MS);
    return () => {
      window.clearInterval(id);
    };
  }, [running, dispatch]);
}
