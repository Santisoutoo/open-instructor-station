/**
 * Failure endpoints injected into the shared API slice — `server/failure_routes.py`.
 *
 * `getFailuresStatus` is the one endpoint meant to be **polled** (design §7.2,
 * `pollingInterval: 2000` applied by `FailuresPanel`): the active set changes
 * server-side whenever a trigger fires or a teleport repairs everything behind the
 * scheduler's back (D10), so the client cannot maintain it itself. Every mutation still
 * writes its response straight into the `getFailuresStatus` cache through
 * `onQueryStarted` for an instant chip update — the next poll tick would confirm the
 * same thing a couple of seconds later regardless, this just avoids the visible lag.
 *
 * Per D15, this adds files rather than editing `instructorApi.ts`.
 */

import { instructorApi } from '../../api/instructorApi';
import type {
  ArmedFailure,
  ArmFailureRequest,
  ClearFailureRequest,
  FailureCatalogueResponse,
  FailuresStatus,
  InjectFailureRequest,
} from '../../api/models';

export const failuresApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    /** The whole catalogue, merged with the adapter's support manifest. Capability-free. */
    getFailuresCatalogue: builder.query<FailureCatalogueResponse, void>({
      query: () => 'failures/catalogue',
    }),
    /** Active failures (sim truth, D10) plus armed ones (the scheduler). Meant to be polled. */
    getFailuresStatus: builder.query<FailuresStatus, void>({
      query: () => 'failures/status',
      // The cache *is* the board the panel renders; never let an unmounted panel expire it.
      keepUnusedDataFor: 3600,
    }),
    /** Fail one system now (D13: immediate, no staging bar). A no-op if already failed. */
    failNow: builder.mutation<FailuresStatus, InjectFailureRequest>({
      query: (body) => ({ url: 'failures/inject', method: 'POST', body }),
      async onQueryStarted(_body, { dispatch, queryFulfilled }) {
        const { data: status } = await queryFulfilled;
        dispatch(
          failuresApi.util.updateQueryData('getFailuresStatus', undefined, () => status),
        );
      },
    }),
    /** Arm a failure on a trigger. Not idempotent — arming twice arms two entries. */
    armFailure: builder.mutation<ArmedFailure, ArmFailureRequest>({
      query: (body) => ({ url: 'failures/arm', method: 'POST', body }),
      async onQueryStarted(_body, { dispatch, queryFulfilled }) {
        const { data: armed } = await queryFulfilled;
        dispatch(
          failuresApi.util.updateQueryData('getFailuresStatus', undefined, (draft) => {
            draft.armed.push(armed);
          }),
        );
      },
    }),
    /** Disarm one armed failure before it fires, by its server-assigned `armed_id`. */
    disarmFailure: builder.mutation<FailuresStatus, string>({
      query: (armedId) => ({ url: `failures/armed/${armedId}`, method: 'DELETE' }),
      async onQueryStarted(_armedId, { dispatch, queryFulfilled }) {
        const { data: status } = await queryFulfilled;
        dispatch(
          failuresApi.util.updateQueryData('getFailuresStatus', undefined, () => status),
        );
      },
    }),
    /** Repair one active failure. A no-op if it is not currently failed. */
    clearFailure: builder.mutation<FailuresStatus, ClearFailureRequest>({
      query: (body) => ({ url: 'failures/clear', method: 'POST', body }),
      async onQueryStarted(_body, { dispatch, queryFulfilled }) {
        const { data: status } = await queryFulfilled;
        dispatch(
          failuresApi.util.updateQueryData('getFailuresStatus', undefined, () => status),
        );
      },
    }),
    /** Repair every active failure and disarm every armed one (D12) — the one-tap reset. */
    clearAllFailures: builder.mutation<FailuresStatus, void>({
      query: () => ({ url: 'failures/clear-all', method: 'POST' }),
      async onQueryStarted(_arg, { dispatch, queryFulfilled }) {
        const { data: status } = await queryFulfilled;
        dispatch(
          failuresApi.util.updateQueryData('getFailuresStatus', undefined, () => status),
        );
      },
    }),
  }),
});

export const {
  useGetFailuresCatalogueQuery,
  useGetFailuresStatusQuery,
  useFailNowMutation,
  useArmFailureMutation,
  useDisarmFailureMutation,
  useClearFailureMutation,
  useClearAllFailuresMutation,
} = failuresApi;
