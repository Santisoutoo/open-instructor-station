/**
 * Cockpit Control Catalog endpoints injected into the shared API slice —
 * `server/cockpit_routes.py` (design §2, §7.2).
 *
 * `getCockpitState` takes the scope the *component* is showing, never a fixed shape: a
 * selected panel scopes the request to that panel's readable controls (D13 — the reason
 * the endpoint exists at all is to avoid reading a hundreds-of-entries catalog wholesale
 * every poll tick); an active cross-panel search asks for every readable control instead,
 * because a match can be on a panel that is not the one currently selected.
 *
 * `actuateCockpitControl` patches every currently cached `getCockpitState` variant
 * straight from the actuation's own confirmed read-back (`onQueryStarted` +
 * `selectCachedArgsForQuery` — a panel-scoped cache entry and a search-flattened one may
 * both be live at once, so "the" cache entry is not a single thing): the response already
 * carries the CONFIRMED value (D8), and waiting for the next poll tick would show a stale
 * one for up to `STATE_POLL_MS`. It invalidates both tags only when the response's
 * `revision` disagrees with the cached catalog's — the aircraft changed underneath the
 * request (D7's swap detector, made visible to the UI per D13). `refreshCockpitCatalog`
 * always bumps the revision (D1), so it invalidates unconditionally.
 */

import { instructorApi } from '../../api/instructorApi';
import type {
  CockpitActuation,
  CockpitActuationResult,
  CockpitCatalogManifest,
  CockpitStateSnapshot,
} from '../../api/models';

export const cockpitApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    /** The active catalog for the loaded aircraft. Capability-free (D1): always 200. */
    getCockpitCatalog: builder.query<CockpitCatalogManifest, void>({
      query: () => 'cockpit/catalog',
      providesTags: ['CockpitCatalog'],
    }),
    /** Confirmed values of the readable controls, optionally scoped to one panel. */
    getCockpitState: builder.query<CockpitStateSnapshot, { panel?: string }>({
      query: ({ panel }) => ({
        url: 'cockpit/state',
        params: panel === undefined ? {} : { panel },
      }),
      providesTags: ['CockpitState'],
    }),
    /** One actuation, confirmed by the adapter's own read-back before the response returns. */
    actuateCockpitControl: builder.mutation<CockpitActuationResult, CockpitActuation>({
      query: (body) => ({ url: 'cockpit/actuate', method: 'POST', body }),
      async onQueryStarted(actuation, { dispatch, getState, queryFulfilled }) {
        const { data: result } = await queryFulfilled;

        for (const arg of cockpitApi.util.selectCachedArgsForQuery(
          getState(),
          'getCockpitState',
        )) {
          dispatch(
            cockpitApi.util.updateQueryData('getCockpitState', arg, (draft) => {
              const row = draft.states.find(
                (entry) => entry.control_id === actuation.control_id,
              );
              if (row !== undefined) {
                row.value = result.state.value;
              } else {
                draft.states.push(result.state);
              }
            }),
          );
        }

        const cachedCatalog = cockpitApi.endpoints.getCockpitCatalog.select()(getState());
        if (
          cachedCatalog.data !== undefined &&
          cachedCatalog.data.revision !== result.revision
        ) {
          dispatch(cockpitApi.util.invalidateTags(['CockpitCatalog', 'CockpitState']));
        }
      },
    }),
    /** Force re-detection and drop every cached binding id. Idempotent. */
    refreshCockpitCatalog: builder.mutation<CockpitCatalogManifest, void>({
      query: () => ({ url: 'cockpit/catalog/refresh', method: 'POST' }),
      invalidatesTags: ['CockpitCatalog', 'CockpitState'],
    }),
  }),
});

export const {
  useGetCockpitCatalogQuery,
  useGetCockpitStateQuery,
  useActuateCockpitControlMutation,
  useRefreshCockpitCatalogMutation,
} = cockpitApi;
