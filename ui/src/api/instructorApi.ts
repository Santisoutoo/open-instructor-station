import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import type {
  AircraftControlManifest,
  AircraftSetup,
  AircraftSetupResult,
  AircraftState,
  ApplyPlacementRequest,
  Capabilities,
  HealthResponse,
  Hold,
  Ils,
  NavdataStatus,
  ParkingKind,
  ParkingStand,
  PlacementPreview,
  PlacementRequest,
  PlacementResult,
  Procedure,
  ProcedureKind,
  ProcedureSummary,
  Runway,
  AirportSummary,
} from './models';

/**
 * Server state lives in RTK Query, never in a hand-rolled slice (CLAUDE.md: RTK Query for
 * server state). Requests go to the relative `/api` prefix so the same build works behind
 * the Vite dev proxy and behind FastAPI in production.
 */
export const instructorApi = createApi({
  reducerPath: 'instructorApi',
  baseQuery: fetchBaseQuery({ baseUrl: '/api' }),
  tagTypes: [
    'Health',
    'Capabilities',
    'AircraftState',
    'AircraftControls',
    'NavdataStatus',
    'Airport',
    'FuelPayload',
    'Profiles',
    // Owned by `features/camera/cameraApi.ts`, declared here because RTK Query
    // resolves tag types at `createApi` time — `injectEndpoints` cannot add one.
    'CameraPositions',
  ],
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

    // ----------------------------------------------------------- navdata
    /**
     * What the navdata provider can answer, and why not when it cannot.
     *
     * The Position panel gates on this exactly as it gates on `Capabilities`. While the
     * index is building the panel polls it; `pollingInterval` is set by the component,
     * not here, because only the component knows whether it is on screen.
     */
    getNavdataStatus: builder.query<NavdataStatus, void>({
      query: () => 'navdata/status',
      providesTags: ['NavdataStatus'],
    }),
    /** Start building the index. Idempotent: a second call while one runs is a no-op. */
    buildNavdataIndex: builder.mutation<NavdataStatus, void>({
      query: () => ({ url: 'navdata/index', method: 'POST' }),
      invalidatesTags: ['NavdataStatus'],
    }),
    /**
     * Type-ahead over every airport in the index.
     *
     * The wire parameter is `q`, as the navdata design specifies. The argument keeps the
     * longer name because `query` is also RTK Query's own key for the request descriptor,
     * and two different `query`s in one object literal reads as a mistake.
     */
    searchAirports: builder.query<AirportSummary[], { query: string; limit?: number }>({
      query: ({ query, limit = 12 }) => ({
        url: 'navdata/airports',
        params: { q: query, limit },
      }),
    }),
    /** Every runway **end** of an airport: 18L and 36R are two entries. */
    getRunways: builder.query<Runway[], string>({
      query: (icao) => `navdata/airports/${icao}/runways`,
      providesTags: (_result, _error, icao) => [{ type: 'Airport', id: icao }],
    }),
    /**
     * The ILS of one runway end. A runway without one answers 404, which is an ordinary
     * outcome here — the badge simply does not render.
     */
    getIls: builder.query<Ils, { icao: string; runwayIdent: string }>({
      query: ({ icao, runwayIdent }) =>
        `navdata/airports/${icao}/runways/${runwayIdent}/ils`,
    }),
    getParking: builder.query<ParkingStand[], { icao: string; kind?: ParkingKind }>({
      query: ({ icao, kind }) => ({
        url: `navdata/airports/${icao}/parking`,
        params: kind === undefined ? {} : { kind },
      }),
      providesTags: (_result, _error, { icao }) => [{ type: 'Airport', id: icao }],
    }),
    getProcedures: builder.query<
      ProcedureSummary[],
      { icao: string; kind?: ProcedureKind }
    >({
      query: ({ icao, kind }) => ({
        url: `navdata/airports/${icao}/procedures`,
        params: kind === undefined ? {} : { kind },
      }),
      providesTags: (_result, _error, { icao }) => [{ type: 'Airport', id: icao }],
    }),
    getProcedure: builder.query<
      Procedure,
      { icao: string; kind: ProcedureKind; ident: string; transition?: string | null }
    >({
      query: ({ icao, kind, ident, transition }) => ({
        url: `navdata/airports/${icao}/procedures/${kind}/${ident}`,
        params: transition == null ? {} : { transition },
      }),
    }),
    getHolds: builder.query<Hold[], { airportIcao?: string; fixIdent?: string }>({
      query: ({ airportIcao, fixIdent }) => ({
        url: 'navdata/holds',
        params: {
          ...(airportIcao === undefined ? {} : { airport_icao: airportIcao }),
          ...(fixIdent === undefined ? {} : { fix_ident: fixIdent }),
        },
      }),
    }),

    // ---------------------------------------------------------- position
    /**
     * Resolve a placement **without moving anything**.
     *
     * A query rather than a mutation despite being a POST: it is side-effect-free by
     * design, and modelling it as a query is what lets the staging bar re-run it on every
     * edit and get caching and de-duplication for free.
     */
    previewPlacement: builder.query<PlacementPreview, PlacementRequest>({
      query: (request) => ({ url: 'position/preview', method: 'POST', body: request }),
    }),
    /** Commit a staged placement. This is the one call that moves the aircraft. */
    applyPlacement: builder.mutation<PlacementResult, ApplyPlacementRequest>({
      query: (body) => ({ url: 'position/apply', method: 'POST', body }),
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
  useGetNavdataStatusQuery,
  useBuildNavdataIndexMutation,
  useSearchAirportsQuery,
  useGetRunwaysQuery,
  useGetIlsQuery,
  useGetParkingQuery,
  useGetProceduresQuery,
  useGetProcedureQuery,
  useGetHoldsQuery,
  usePreviewPlacementQuery,
  useApplyPlacementMutation,
} = instructorApi;
