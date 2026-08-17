/**
 * Server state for the Scenarios panel, injected into the shared RTK Query API.
 *
 * The scenario catalogue is server state — the backend owns which scenarios exist and
 * whether the active adapter can run them — so it lives here and never in the slice.
 */

import { instructorApi } from '../../api/instructorApi';
import { withLatency } from '../../mocks/latency';
import { MOCK_SCENARIOS, type Scenario } from './mock';

export const scenariosApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    // MOCK: replace queryFn with query('/scenarios') at backend integration.
    getScenarios: builder.query<Scenario[], void>({
      queryFn: () => withLatency(MOCK_SCENARIOS),
    }),
  }),
});

export const { useGetScenariosQuery } = scenariosApi;
