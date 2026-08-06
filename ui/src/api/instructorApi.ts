import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import type { AircraftState, Capabilities, HealthResponse } from './types';

/**
 * Server state lives in RTK Query, never in a hand-rolled slice (CLAUDE.md: RTK Query for
 * server state). Requests go to the relative `/api` prefix so the same build works behind
 * the Vite dev proxy and behind FastAPI in production.
 */
export const instructorApi = createApi({
  reducerPath: 'instructorApi',
  baseQuery: fetchBaseQuery({ baseUrl: '/api' }),
  tagTypes: ['Health', 'Capabilities', 'AircraftState'],
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
  }),
});

export const { useGetHealthQuery, useGetCapabilitiesQuery, useGetStateQuery } =
  instructorApi;
