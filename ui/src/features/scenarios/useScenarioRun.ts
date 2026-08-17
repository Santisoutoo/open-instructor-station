/**
 * Bridges the polled run status into the panel and the status bar.
 *
 * The server owns run progress (`GET /api/scenarios/run`, `server/scenario_engine.py`);
 * this module owns only what the server cannot: *when* to poll, and (for the panel)
 * whether the instructor has dismissed the bar for the run currently in the cache.
 *
 * `useScenarioRunStatus` is the one place that actually subscribes — every caller gets
 * an active `useGetScenarioRunQuery`, not a passive `useQueryState` read, precisely
 * because `StatusBar` is always mounted while `ScenariosPanel` is not (every tab except
 * `map` unmounts on tab switch, `ui/src/components/tabs.ts`). A passive read in
 * `StatusBar` would go stale the moment the instructor left the Scenarios tab: the
 * fetch itself would never happen, and a run that later failed server-side would keep
 * showing "running" in the footer indefinitely. RTK Query merges concurrent
 * subscriptions to the same query, so `StatusBar` and `ScenariosPanel` mounted together
 * cost one fetch, not two.
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

/** The one active subscription to `GET /api/scenarios/run`. Safe to call from more than
 * one mounted component at once — see the module docstring. */
export function useScenarioRunStatus(): ScenarioRunStatus | null {
  const cached = useGetScenarioRunState();
  const { data } = useGetScenarioRunQuery(undefined, {
    pollingInterval: cached.data?.status === 'running' ? RUN_POLL_MS : 0,
    skipPollingIfUnfocused: true,
  });

  return data ?? null;
}

export interface ScenarioRunView {
  /** The run to show, or `null` when there is none or it has been dismissed. */
  run: ScenarioRunStatus | null;
  /** Hide the bar client-side. The run itself keeps going server-side regardless. */
  dismiss: () => void;
}

export function useScenarioRun(): ScenarioRunView {
  const dispatch = useAppDispatch();
  const dismissedKey = useAppSelector((state) => state.scenarios.dismissedRunKey);

  const run = useScenarioRunStatus();
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
