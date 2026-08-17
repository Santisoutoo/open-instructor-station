/**
 * Mock traffic endpoints injected into the shared API slice.
 *
 * The `getActiveTraffic` cache is the single source of truth for what is spawned:
 * mutations write into it through `onQueryStarted` + `updateQueryData` (pessimistic —
 * after the mock latency resolves, matching how the bridge will confirm), and the
 * movement hook advances it in place. Entities therefore persist across tab switches
 * exactly as they will once a real bridge owns them.
 */

// MOCK: replace queryFn with query('/traffic...') at backend integration.

import { instructorApi } from '../../api/instructorApi';
import { withLatency } from '../../mocks/latency';
import { buildSpawn, trafficManifestFixture } from './mock';
import type { SpawnRequest, TrafficEntity, TrafficManifest } from './types.mock';

export const trafficApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    getTrafficManifest: builder.query<TrafficManifest, void>({
      queryFn: () => withLatency(trafficManifestFixture()),
    }),
    getActiveTraffic: builder.query<TrafficEntity[], void>({
      queryFn: () => withLatency<TrafficEntity[]>([]),
      // The cache *is* the spawned traffic; never let an unmounted panel expire it.
      keepUnusedDataFor: 3600,
    }),
    spawnTraffic: builder.mutation<TrafficEntity[], SpawnRequest>({
      queryFn: (request) => withLatency(buildSpawn(request)),
      async onQueryStarted(_request, { dispatch, queryFulfilled }) {
        const { data: spawned } = await queryFulfilled;
        dispatch(
          trafficApi.util.updateQueryData('getActiveTraffic', undefined, (draft) => {
            draft.push(...spawned);
          }),
        );
      },
    }),
    despawnTraffic: builder.mutation<{ id: string }, string>({
      queryFn: (id) => withLatency({ id }),
      async onQueryStarted(id, { dispatch, queryFulfilled }) {
        await queryFulfilled;
        dispatch(
          trafficApi.util.updateQueryData('getActiveTraffic', undefined, (draft) =>
            draft.filter((entity) => entity.id !== id),
          ),
        );
      },
    }),
    despawnAllTraffic: builder.mutation<null, void>({
      queryFn: () => withLatency(null),
      async onQueryStarted(_arg, { dispatch, queryFulfilled }) {
        await queryFulfilled;
        dispatch(
          trafficApi.util.updateQueryData('getActiveTraffic', undefined, () => []),
        );
      },
    }),
  }),
});

export const {
  useGetTrafficManifestQuery,
  useGetActiveTrafficQuery,
  useSpawnTrafficMutation,
  useDespawnTrafficMutation,
  useDespawnAllTrafficMutation,
} = trafficApi;
