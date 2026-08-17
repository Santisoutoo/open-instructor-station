/**
 * Mock failure endpoints injected into the shared API slice.
 *
 * The `getFailureBoard` cache is the single source of truth for what is active and
 * armed: mutations write into it through `onQueryStarted` + `updateQueryData`
 * (pessimistic — after the mock latency resolves, matching how the server will
 * confirm), and the trigger hook promotes armed entries in place. The board therefore
 * persists across tab switches exactly as it will once the server owns it.
 */

// MOCK: replace queryFn with query('/failures...') at backend integration.

import { instructorApi } from '../../api/instructorApi';
import { withLatency } from '../../mocks/latency';
import { buildActive, buildArmed, FAILURE_CATALOGUE, failuresManifestFixture } from './mock';
import type {
  ActiveFailure,
  ArmedFailure,
  ArmRequest,
  FailureDefinition,
  FailuresBoard,
  FailuresManifest,
} from './types.mock';

export const failuresApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    getFailuresManifest: builder.query<FailuresManifest, void>({
      queryFn: () => withLatency(failuresManifestFixture()),
    }),
    getFailureCatalogue: builder.query<FailureDefinition[], void>({
      queryFn: () => withLatency<FailureDefinition[]>([...FAILURE_CATALOGUE]),
    }),
    getFailureBoard: builder.query<FailuresBoard, void>({
      queryFn: () => withLatency<FailuresBoard>({ active: [], armed: [] }),
      // The cache *is* the board; never let an unmounted panel expire it.
      keepUnusedDataFor: 3600,
    }),
    failNow: builder.mutation<ActiveFailure, string>({
      queryFn: (failureId) => withLatency(buildActive(failureId)),
      async onQueryStarted(failureId, { dispatch, queryFulfilled }) {
        const { data: active } = await queryFulfilled;
        dispatch(
          failuresApi.util.updateQueryData('getFailureBoard', undefined, (draft) => {
            // Failing now supersedes any pending trigger for the same failure.
            draft.armed = draft.armed.filter((armed) => armed.failureId !== failureId);
            if (!draft.active.some((entry) => entry.failureId === failureId)) {
              draft.active.push(active);
            }
          }),
        );
      },
    }),
    armFailure: builder.mutation<ArmedFailure, ArmRequest>({
      queryFn: (request) => withLatency(buildArmed(request)),
      async onQueryStarted(request, { dispatch, queryFulfilled }) {
        const { data: armed } = await queryFulfilled;
        dispatch(
          failuresApi.util.updateQueryData('getFailureBoard', undefined, (draft) => {
            // Re-arming replaces the previous trigger rather than stacking one per arm.
            draft.armed = draft.armed.filter(
              (entry) => entry.failureId !== request.failureId,
            );
            draft.armed.push(armed);
          }),
        );
      },
    }),
    /** Clears one failure wherever it is — active, armed, or both. */
    clearFailure: builder.mutation<{ id: string }, string>({
      queryFn: (failureId) => withLatency({ id: failureId }),
      async onQueryStarted(failureId, { dispatch, queryFulfilled }) {
        await queryFulfilled;
        dispatch(
          failuresApi.util.updateQueryData('getFailureBoard', undefined, (draft) => {
            draft.active = draft.active.filter((entry) => entry.failureId !== failureId);
            draft.armed = draft.armed.filter((entry) => entry.failureId !== failureId);
          }),
        );
      },
    }),
    clearAllFailures: builder.mutation<null, void>({
      queryFn: () => withLatency(null),
      async onQueryStarted(_arg, { dispatch, queryFulfilled }) {
        await queryFulfilled;
        dispatch(
          failuresApi.util.updateQueryData('getFailureBoard', undefined, () => ({
            active: [],
            armed: [],
          })),
        );
      },
    }),
  }),
});

export const {
  useGetFailuresManifestQuery,
  useGetFailureCatalogueQuery,
  useGetFailureBoardQuery,
  useFailNowMutation,
  useArmFailureMutation,
  useClearFailureMutation,
  useClearAllFailuresMutation,
} = failuresApi;
