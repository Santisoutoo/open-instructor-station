/**
 * Mock weather endpoints injected into the shared API slice.
 *
 * The `getWeatherState` cache is the single source of truth for what the
 * environment is: the apply mutation writes into it through `onQueryStarted` +
 * `updateQueryData` (pessimistic — after the mock latency resolves, matching how
 * the server will confirm), so the applied weather survives tab switches exactly
 * as it will once a real adapter owns it.
 */

// MOCK: replace queryFn with query('/weather...') at backend integration.

import { instructorApi } from '../../api/instructorApi';
import { withLatency } from '../../mocks/latency';
import { initialWeatherFixture, resolveAppliedWeather } from './mock';
import type { ApplyWeatherRequest, WeatherState } from './types.mock';

export const weatherApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    getWeatherState: builder.query<WeatherState, void>({
      queryFn: () => withLatency(initialWeatherFixture()),
      // The cache *is* the applied weather; never let an unmounted panel expire it.
      keepUnusedDataFor: 3600,
    }),
    applyWeather: builder.mutation<WeatherState, ApplyWeatherRequest>({
      queryFn: (request) => withLatency(resolveAppliedWeather(request)),
      async onQueryStarted(_request, { dispatch, queryFulfilled }) {
        const { data: applied } = await queryFulfilled;
        dispatch(
          weatherApi.util.updateQueryData('getWeatherState', undefined, () => applied),
        );
      },
    }),
  }),
});

export const { useGetWeatherStateQuery, useApplyWeatherMutation } = weatherApi;
