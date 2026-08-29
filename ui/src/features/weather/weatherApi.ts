/**
 * Weather endpoints injected into the shared API slice.
 *
 * `getWeatherState` is the single source of truth for what the environment is: the apply
 * mutation writes into it through `onQueryStarted` + `updateQueryData`, using the read-back
 * `state` the server already sent back with the apply result — the same shape the mock
 * version kept, now filled from a real response instead of a simulated one. No tag types
 * are added to the shared `instructorApi` for this: the manual cache write keeps the Weather
 * Manager self-contained, exactly as the mock version already was (CLAUDE.md: adding a
 * manager must not require touching the others).
 *
 * `previewWeather` is a `query`, not a `mutation`, despite being a POST — it is
 * side-effect-free by design (server/weather_routes.py: preview never touches the adapter),
 * which is what lets `WeatherPanel` re-run it whenever the staged preset or the selected
 * runway changes and get RTK Query's own caching and de-duplication for free. The
 * instructor's own edits are merged client-side instead of re-triggering it — see
 * `WeatherPanel.tsx`. Mirrors `previewPlacement` in `features/position/StagingBar.tsx`.
 */

import { instructorApi } from '../../api/instructorApi';
import type {
  WeatherApplyResult,
  WeatherManifest,
  WeatherPreview,
  WeatherRequest,
  WeatherState,
} from '../../api/models';

export const weatherApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    getWeatherState: builder.query<WeatherState, void>({
      query: () => 'weather',
      // The cache *is* the applied weather; never let an unmounted panel expire it.
      keepUnusedDataFor: 3600,
    }),
    getWeatherManifest: builder.query<WeatherManifest, void>({
      query: () => 'weather/manifest',
    }),
    previewWeather: builder.query<WeatherPreview, WeatherRequest>({
      query: (request) => ({ url: 'weather/preview', method: 'POST', body: request }),
    }),
    applyWeather: builder.mutation<WeatherApplyResult, WeatherRequest>({
      query: (request) => ({ url: 'weather/apply', method: 'POST', body: request }),
      async onQueryStarted(_request, { dispatch, queryFulfilled }) {
        try {
          const { data: result } = await queryFulfilled;
          dispatch(
            weatherApi.util.updateQueryData(
              'getWeatherState',
              undefined,
              () => result.state,
            ),
          );
        } catch {
          // A failed apply is rendered from the mutation's own error state
          // (`WeatherPanel`'s `applyState.isError`); nothing to update here.
        }
      },
    }),
  }),
});

export const {
  useGetWeatherStateQuery,
  useGetWeatherManifestQuery,
  usePreviewWeatherQuery,
  useApplyWeatherMutation,
} = weatherApi;
