/**
 * Server state for the Scenarios panel, injected into the shared RTK Query API —
 * `server/scenario_routes.py`.
 *
 * `getScenarios` returns the manifest wrapper — `{ adapter, scenarios, load_errors }` —
 * not a bare array; callers read `.scenarios` off it (design §7.1, D15: adding this
 * manager adds files, `instructorApi.ts` is untouched).
 *
 * `runScenario` invalidates `AircraftState`: running a scenario writes weather/position/
 * failures against the live adapter, so any panel watching the one-shot `GET /api/state`
 * snapshot must refetch. It also writes its own response straight into the
 * `getScenarioRun` cache through `onQueryStarted`, the same "instant chip update" pattern
 * `failuresApi.ts` uses — the bar appears with the full pending checklist immediately,
 * rather than waiting for the first poll tick.
 *
 * `getScenarioRun` is the one source of truth for a run's progress. *When* to poll it —
 * only while the most recently known run is still `"running"` — is decided by the caller
 * (`useScenarioRun.ts`), mirroring `features/position/PositionPanel.tsx`'s navdata-status
 * polling: only the component knows whether the run view is on screen.
 */

import { instructorApi } from '../../api/instructorApi';
import type { ScenarioDetail, ScenarioManifest, ScenarioRunStatus } from '../../api/models';

export const scenariosApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    getScenarios: builder.query<ScenarioManifest, void>({
      query: () => 'scenarios',
    }),
    getScenario: builder.query<ScenarioDetail, string>({
      query: (id) => `scenarios/${id}`,
    }),
    /** Pre-flight check, then start the background run. 409/501 surface as `error`. */
    runScenario: builder.mutation<ScenarioRunStatus, string>({
      query: (id) => ({ url: `scenarios/${id}/run`, method: 'POST' }),
      invalidatesTags: ['AircraftState'],
      async onQueryStarted(_id, { dispatch, queryFulfilled }) {
        try {
          const { data: status } = await queryFulfilled;
          dispatch(
            scenariosApi.util.updateQueryData('getScenarioRun', undefined, () => status),
          );
        } catch {
          // A failed run start is rendered from the mutation's own error state
          // (`ScenariosPanel`'s `runScenarioState.isError`); nothing to update here.
        }
      },
    }),
    /** The current or most recently finished run. `null` body when nothing has run. */
    getScenarioRun: builder.query<ScenarioRunStatus | null, void>({
      query: () => 'scenarios/run',
      // The cache *is* the bar the panel renders; never let an unmounted panel expire it.
      keepUnusedDataFor: 3600,
    }),
  }),
});

export const {
  useGetScenariosQuery,
  useGetScenarioQuery,
  useRunScenarioMutation,
  useGetScenarioRunQuery,
} = scenariosApi;
