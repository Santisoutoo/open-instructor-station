/**
 * Fuel & Payload endpoints injected into the shared API slice (D16 of
 * `docs/designs/fuel-payload.md` — never editing `instructorApi.ts`'s endpoint map
 * directly, the Position panel's own recorded regret).
 *
 * `previewFuelPayload` is a **query** despite being a POST: it is side-effect-free by
 * design (`server/fuel_payload_routes.py` writes nothing on preview — `get_loadout()`
 * is read, `apply_setup` is never called), and modelling it as a query is what lets the
 * staging bar re-run it on every tank/station edit and get RTK Query's caching and
 * de-duplication for free — the `previewPlacement`/weather-preview precedent.
 *
 * `getFuelPayload` carries the `FuelPayload` tag and `applyFuelPayload` invalidates it,
 * so a panel not actively watching the mutation still sees the read-back after an apply.
 */

import { instructorApi } from '../../api/instructorApi';
import type {
  FuelPayloadApplyResult,
  FuelPayloadManifest,
  FuelPayloadPreview,
  FuelPayloadRequest,
  FuelPayloadState,
} from '../../api/models';

export const fuelPayloadApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    /** Capability + reason, resolved mass limits, the preset catalogue. Always 200. */
    getFuelPayloadManifest: builder.query<FuelPayloadManifest, void>({
      query: () => 'fuel-payload/manifest',
    }),
    /** The current loadout plus its computed mass-and-balance. */
    getFuelPayload: builder.query<FuelPayloadState, void>({
      query: () => 'fuel-payload',
      providesTags: ['FuelPayload'],
    }),
    /** Resolve a preset + overlay into the exact loadout `apply` would produce. */
    previewFuelPayload: builder.query<FuelPayloadPreview, FuelPayloadRequest>({
      query: (request) => ({ url: 'fuel-payload/preview', method: 'POST', body: request }),
    }),
    /** Commit a staged loadout. The only call that touches the simulator. */
    applyFuelPayload: builder.mutation<FuelPayloadApplyResult, FuelPayloadRequest>({
      query: (request) => ({ url: 'fuel-payload/apply', method: 'POST', body: request }),
      invalidatesTags: ['FuelPayload'],
    }),
  }),
});

export const {
  useGetFuelPayloadManifestQuery,
  useGetFuelPayloadQuery,
  usePreviewFuelPayloadQuery,
  useApplyFuelPayloadMutation,
} = fuelPayloadApi;
