/**
 * Bridges the polled run status into the panel.
 *
 * The server owns run progress (`GET /api/scenarios/run`, `server/scenario_engine.py`);
 * this hook owns only two things the server cannot: *when* to poll, and whether the
 * instructor has dismissed the bar for the run currently in the cache.
 *
 * Polling turns on only while the most recently known run is `"running"` — the same
 * "read the cache before the query that answers it" shape
 * `features/position/PositionPanel.tsx` uses for navdata-status polling, so deciding the
 * interval never opens a second subscription. Once a run settles (`"completed"` /
 * `"failed"`), polling stops on its own; `getScenarioRun`'s `keepUnusedDataFor` keeps that
 * final snapshot in the cache for the rest of the session.
 */

import { useAppDispatch, useAppSelector } from '../../store';
import { runKey } from './format';
import { scenariosApi, useGetScenarioRunQuery } from './scenariosApi';
import { runDismissed } from './scenariosSlice';
import type { ScenarioRunStatus } from '../../api/models';

const RUN_POLL_MS = 1000;

const useGetScenarioRunState = scenariosApi.endpoints.getScenarioRun.useQueryState;

export interface ScenarioRunView {
  /** The run to show, or `null` when there is none or it has been dismissed. */
  run: ScenarioRunStatus | null;
  /** Hide the bar client-side. The run itself keeps going server-side regardless. */
  dismiss: () => void;
}

export function useScenarioRun(): ScenarioRunView {
  const dispatch = useAppDispatch();
  const dismissedKey = useAppSelector((state) => state.scenarios.dismissedRunKey);

  const cached = useGetScenarioRunState();
  const { data } = useGetScenarioRunQuery(undefined, {
    pollingInterval: cached.data?.status === 'running' ? RUN_POLL_MS : 0,
    skipPollingIfUnfocused: true,
  });

  const run = data ?? null;
  const visible = run !== null && runKey(run) !== dismissedKey;

  return {
    run: visible ? run : null,
    dismiss: () => {
      if (run !== null) {
        dispatch(runDismissed(runKey(run)));
      }
    },
  };
}
