/**
 * The Instructor Map's own RTK Query endpoints, injected into the shared API slice
 * (instructor-map.md D13): adding this manager adds files, it never edits
 * `instructorApi.ts`. `getRunways`, `getProcedures` and `getProcedure` are NOT
 * re-declared here — they already exist on `instructorApi` and the map imports those
 * hooks directly.
 *
 * `kinds` must serialize as **repeated** query keys (`kinds=vor&kinds=ndb`) to match
 * FastAPI's `Annotated[list[NavaidKind] | None, Query()]`. `fetchBaseQuery`'s default
 * `params` handling comma-joins arrays, which FastAPI rejects as one unknown kind — so
 * the near-queries build their query strings themselves through
 * {@link toRepeatedParams}, exported for the unit test that §8.5 flags as the gate.
 */

import { instructorApi } from '../../api/instructorApi';
import type {
  Airport,
  AirportSummary,
  Fix,
  MeasureResult,
  Navaid,
  NavaidKind,
} from '../../api/models';
import type { LatLon } from './measure';

/** One query-string value: scalars appear once, arrays appear once **per element**. */
type ParamValue = string | number | readonly string[] | undefined;

/**
 * Build a query string in which an array value becomes a repeated key, never a
 * comma-joined one. Pure, and exported so the serialization risk called out in
 * instructor-map.md §10.7 is pinned by a test instead of assumed.
 */
export function toRepeatedParams(params: Record<string, ParamValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) {
      continue;
    }
    if (Array.isArray(value)) {
      for (const entry of value as readonly string[]) {
        search.append(key, entry);
      }
    } else {
      search.append(key, String(value));
    }
  }
  return search.toString();
}

export const mapApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    getAirportsNear: builder.query<
      AirportSummary[],
      { lat: number; lon: number; radiusNm: number; limit?: number }
    >({
      query: ({ lat, lon, radiusNm, limit = 30 }) =>
        `navdata/airports/near?${toRepeatedParams({ lat, lon, radius_nm: radiusNm, limit })}`,
    }),
    getNavaidsNear: builder.query<
      Navaid[],
      { lat: number; lon: number; radiusNm: number; kinds?: NavaidKind[]; limit?: number }
    >({
      query: ({ lat, lon, radiusNm, kinds, limit = 100 }) =>
        `navdata/navaids?${toRepeatedParams({ lat, lon, radius_nm: radiusNm, limit, kinds })}`,
    }),
    getFixesNear: builder.query<
      Fix[],
      { lat: number; lon: number; radiusNm: number; limit?: number }
    >({
      query: ({ lat, lon, radiusNm, limit = 150 }) =>
        `navdata/fixes?${toRepeatedParams({ lat, lon, radius_nm: radiusNm, limit })}`,
    }),
    /**
     * One airport in full — the reference airport's elevation feeds the METAR chip's
     * AGL cloud bases, and its position is where the picker eases the camera.
     */
    getAirport: builder.query<Airport, string>({
      query: (icao) => `navdata/airports/${icao}`,
    }),
    /**
     * The exact WGS84 measure (instructor-map.md D9): replaces the live spherical
     * readout once both points are settled. A query, so re-measuring the same pair
     * is a cache hit, not a round trip.
     */
    measureGeodesic: builder.query<MeasureResult, { a: LatLon; b: LatLon }>({
      query: ({ a, b }) => ({
        url: 'geodesy/measure',
        params: { lat1: a.lat, lon1: a.lon, lat2: b.lat, lon2: b.lon },
      }),
    }),
  }),
});

export const {
  useGetAirportsNearQuery,
  useGetNavaidsNearQuery,
  useGetFixesNearQuery,
  useGetAirportQuery,
  useMeasureGeodesicQuery,
} = mapApi;
