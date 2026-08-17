/**
 * Server state for the Landing Analysis panel, injected into the shared RTK Query
 * API. Recorded landings are server state — the backend records and analyses them;
 * the UI only picks one and draws it.
 */

import { instructorApi } from '../../api/instructorApi';
import { withLatency } from '../../mocks/latency';
import { MOCK_LANDINGS } from './mock';
import type { Landing } from './types.mock';

export const landingApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    // MOCK: replace queryFn with query('/landings') at backend integration.
    getLandings: builder.query<Landing[], void>({
      queryFn: () => withLatency(MOCK_LANDINGS),
    }),
  }),
});

export const { useGetLandingsQuery } = landingApi;
