/**
 * Traffic endpoints injected into the shared API slice — `server/traffic_routes.py`.
 *
 * Per D13 this adds files rather than editing `instructorApi.ts`; only the `Traffic` tag
 * type is declared there, exactly as `FuelPayload` and `Profiles` are.
 *
 * **The contact list does not come from here.** `WS /ws/traffic` pushes the full picture
 * at 2 Hz (D10), so polling `GET /status` for it would be the same mistake as polling
 * `/api/state` next to `/ws/state` (design §7.2). `getTrafficStatus` is fetched once for
 * what the stream does not carry — the adapter's name and its `max_contacts` capacity —
 * and re-fetched after every write, which also makes it an honest fallback list for the
 * window before the socket's first frame and for a session where the socket is down.
 */

import { instructorApi } from '../../api/instructorApi';
import type {
  TrafficSpawnRequest,
  TrafficSpawnResult,
  TrafficStatus,
} from '../../api/models';

export const trafficApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    /**
     * Every live contact, the adapter's name and its capacity. **Capability-free**
     * (design §2.1): an adapter without `can_spawn_traffic` answers `contacts: []`
     * rather than 501, so this query is issued even while the panel's gate is shut.
     */
    getTrafficStatus: builder.query<TrafficStatus, void>({
      query: () => 'traffic/status',
      providesTags: ['Traffic'],
    }),
    /**
     * Resolve one instructor intent into tracks and spawn each. Not idempotent —
     * spawning twice creates two entities. 409 when the adapter is at capacity, which
     * is transient and therefore reported, never pre-disabled.
     */
    spawnTraffic: builder.mutation<TrafficSpawnResult, TrafficSpawnRequest>({
      query: (body) => ({ url: 'traffic/spawn', method: 'POST', body }),
      invalidatesTags: ['Traffic'],
    }),
    /** Despawn one entity. Idempotent: an already-gone id is a 200 no-op. */
    despawnTraffic: builder.mutation<TrafficStatus, string>({
      query: (trafficId) => ({ url: `traffic/${trafficId}`, method: 'DELETE' }),
      invalidatesTags: ['Traffic'],
    }),
    /** Despawn everything the adapter is tracking — the one-tap reset. Idempotent. */
    clearAllTraffic: builder.mutation<TrafficStatus, void>({
      query: () => ({ url: 'traffic/clear', method: 'POST' }),
      invalidatesTags: ['Traffic'],
    }),
  }),
});

export const {
  useGetTrafficStatusQuery,
  useSpawnTrafficMutation,
  useDespawnTrafficMutation,
  useClearAllTrafficMutation,
} = trafficApi;
