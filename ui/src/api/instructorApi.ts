import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import type {
  AircraftControlManifest,
  AircraftSetup,
  AircraftSetupResult,
  AircraftState,
  Capabilities,
  HealthResponse,
} from './models';

/**
 * Server state lives in RTK Query, never in a hand-rolled slice (CLAUDE.md: RTK Query for
 * server state). Requests go to the relative `/api` prefix so the same build works behind
 * the Vite dev proxy and behind FastAPI in production.
 */
export const instructorApi = createApi({
  reducerPath: 'instructorApi',
  baseQuery: fetchBaseQuery({ baseUrl: '/api' }),
  tagTypes: ['Health', 'Capabilities', 'AircraftState', 'AircraftControls'],
  endpoints: (builder) => ({
    getHealth: builder.query<HealthResponse, void>({
      query: () => 'health',
      providesTags: ['Health'],
    }),
    getCapabilities: builder.query<Capabilities, void>({
      query: () => 'capabilities',
      providesTags: ['Capabilities'],
    }),
    /**
     * One-shot snapshot. The continuous feed is the WebSocket in
     * `features/telemetry/useTelemetrySocket.ts`; this endpoint only seeds the panel
     * before the socket delivers its first frame.
     */
    getState: builder.query<AircraftState, void>({
      query: () => 'state',
      providesTags: ['AircraftState'],
    }),
    /**
     * Which Aircraft Control panel controls may be written, and why the rest may not.
     *
     * Strictly more informative than `getCapabilities`: a capability flag says the adapter
     * can drive an autopilot, this says whether the server has a field to carry the
     * request. The panel disables on this, so a failed fetch must fail *closed* — see
     * `features/aircraft/controls.ts`.
     */
    getAircraftControls: builder.query<AircraftControlManifest, void>({
      query: () => 'aircraft/controls',
      providesTags: ['AircraftControls'],
    }),
    /**
     * Write the aircraft configuration. Idempotent: the body carries target values, not
     * deltas. Invalidates the snapshot so a panel not watching the socket still refreshes.
     */
    applyAircraftSetup: builder.mutation<AircraftSetupResult, AircraftSetup>({
      query: (setup) => ({ url: 'aircraft/setup', method: 'POST', body: setup }),
      invalidatesTags: ['AircraftState'],
    }),
  }),
});

export const {
  useGetHealthQuery,
  useGetCapabilitiesQuery,
  useGetStateQuery,
  useGetAircraftControlsQuery,
  useApplyAircraftSetupMutation,
} = instructorApi;
