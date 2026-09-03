/**
 * The Position screen's reads, in one place.
 *
 * Every one of these is a thin composition over RTK Query — the cache is the state, so a
 * hook called from four components issues one request and the four re-render together.
 * Nothing here holds server data in a slice; `positionDesignSlice` stores only the
 * *identity* of what the instructor picked (CLAUDE.md: RTK Query for server state).
 *
 * A file of hooks and no components, so `react-refresh/only-export-components` is happy and
 * the components stay about layout.
 */

import { useMemo } from 'react';
import {
  useGetCapabilitiesQuery,
  useGetIlsQuery,
  useGetRunwaysQuery,
  usePreviewPlacementQuery,
  useSearchAirportsQuery,
} from '../../api/instructorApi';
import type {
  AirportSummary,
  Ils,
  PlacementPreview,
  PlacementRequest,
  ProcedureKind,
  Runway,
  WeatherState,
} from '../../api/models';
import { useAppSelector } from '../../store';
import { useGetWeatherStateQuery } from '../weather/weatherApi';
import { AIRWORK_LEVEL_FEET } from './airwork';
import { buildPlacementRequest, type PlacementInputs } from './placementRequest';
import type { ProcedureFamily } from './positionDesignSlice';
import { instructorSetup, mergedSetup, type InstructorSetup } from './setup';
import { windComponents } from './wind';

/** The ICAO "Load" last committed, or `''` before the first one. */
export function useLoadedIcao(): string {
  return useAppSelector((state) => state.positionDesign.loadedIcao);
}

/**
 * The loaded airport itself, resolved through the type-ahead endpoint.
 *
 * `GET /api/navdata/airports/{icao}` does exist (`server/navdata_routes.py:203`, consumed
 * elsewhere as `getAirport` in `features/map/mapApi.ts` and by the startup gate,
 * `features/startup/AirportGate.tsx`) — this hook still goes through the search endpoint
 * rather than that one, left unchanged here since switching it is outside this change's
 * scope. An exact ICAO is the narrowest query the search takes, and anything that is not an
 * exact match is discarded, so a partially typed code never silently loads a neighbouring
 * field.
 */
export function useAirport(): {
  readonly airport: AirportSummary | undefined;
  readonly isFetching: boolean;
  readonly isError: boolean;
} {
  const icao = useLoadedIcao();
  const { data, isFetching, isError } = useSearchAirportsQuery(
    { query: icao, limit: 5 },
    { skip: icao === '' },
  );
  return {
    airport: data?.find((entry) => entry.icao === icao),
    isFetching,
    isError,
  };
}

/** Every runway **end** of the loaded airport. */
export function useRunways(): {
  readonly runways: readonly Runway[];
  readonly isFetching: boolean;
  readonly isError: boolean;
} {
  const icao = useLoadedIcao();
  const { data, isFetching, isError } = useGetRunwaysQuery(icao, { skip: icao === '' });
  return { runways: data ?? [], isFetching, isError };
}

/** The selected runway end, or `null` when none is selected or it is not at this airport. */
export function useSelectedRunway(): Runway | null {
  const selected = useAppSelector((state) => state.positionDesign.selectedRunway);
  const { runways } = useRunways();
  return runways.find((runway) => runway.ident === selected) ?? null;
}

/**
 * The ground under the placement, feet MSL — the selected runway's elevation, else the
 * airport's, else `null` when neither is known.
 *
 * It is what turns the preview's altitude MSL into "is this placement airborne", which is
 * the question the speed gate turns on. `null` is honest: with no airport there is no
 * terrain source on this side of the wire, and the gate falls back to sea level as the
 * reference rather than pretending to know better.
 */
export function useGroundElevationFt(): number | null {
  const runway = useSelectedRunway();
  const { airport } = useAirport();
  return runway?.elevation_ft ?? airport?.elevation_ft ?? null;
}

/**
 * The ILS of one runway end.
 *
 * A runway without one answers 404, which is an ordinary outcome: `hasIls` is `false`, not
 * an error. `hasIls` stays `null` until the answer arrives so that nothing downstream
 * reports "no ILS" while the question is still in flight — the same fail-closed posture the
 * capability gates take.
 */
export function useIls(runwayIdent: string | null): {
  readonly ils: Ils | null;
  readonly hasIls: boolean | null;
} {
  const icao = useLoadedIcao();
  const skip = icao === '' || runwayIdent === null;
  const { data, isError, isSuccess } = useGetIlsQuery(
    { icao, runwayIdent: runwayIdent ?? '' },
    { skip },
  );
  if (skip) {
    return { ils: null, hasIls: null };
  }
  if (isSuccess) {
    return { ils: data, hasIls: true };
  }
  return { ils: null, hasIls: isError ? false : null };
}

export interface SurfaceWind {
  readonly directionDeg: number;
  readonly speedKt: number;
}

/**
 * The commanded weather, and the surface wind read off its lowest layer.
 *
 * `GET /api/weather` 501s without `can_set_weather`, so the query is skipped outright until
 * the capability is known true — the same reasoning as `features/map/MetarChip.tsx`. When
 * it is not supported the screen shows "unavailable" and every wind-derived check simply
 * does not fire, rather than firing on a zero.
 */
export function useWeather(): {
  readonly weather: WeatherState | undefined;
  readonly wind: SurfaceWind | null;
  readonly qnhHpa: number | null;
  readonly supported: boolean | null;
} {
  const { data: capabilities } = useGetCapabilitiesQuery();
  const supported = capabilities === undefined ? null : capabilities.can_set_weather;
  const { data: weather } = useGetWeatherStateQuery(undefined, {
    skip: supported !== true,
  });

  const surface = [...(weather?.wind_layers ?? [])].sort(
    (a, b) => a.altitude_ft - b.altitude_ft,
  )[0];
  return {
    weather,
    wind:
      surface === undefined
        ? null
        : { directionDeg: surface.direction_deg, speedKt: surface.speed_kt },
    qnhHpa: weather?.qnh_hpa ?? null,
    supported,
  };
}

/** The tailwind component on a runway, in knots. `null` when either input is unknown. */
export function tailwindOn(
  runway: Runway | null,
  wind: SurfaceWind | null,
): number | null {
  if (runway === null || wind === null) {
    return null;
  }
  return windComponents(wind.directionDeg, wind.speedKt, runway.true_bearing_deg).tail;
}

/** The design tab's four procedure chips, mapped onto the server's three kinds. */
export function procedureKindOf(family: ProcedureFamily): ProcedureKind {
  switch (family) {
    case 'sid':
      return 'sid';
    case 'star':
      return 'star';
    case 'apptr':
    case 'final':
      return 'approach';
  }
}

/**
 * Whether a procedure belongs under a chip.
 *
 * The server publishes three kinds and the screen offers four chips, so `approach` is split
 * on something the data really does carry: an approach with a **named** transition is an
 * approach transition, one without is the common final route.
 */
export function procedureFamilyMatches(
  family: ProcedureFamily,
  transition: string | null | undefined,
): boolean {
  if (family === 'apptr') {
    return transition != null && transition !== '';
  }
  if (family === 'final') {
    return transition == null || transition === '';
  }
  return true;
}

/**
 * The Custom tab's placement, or `null` when its coordinate does not resolve.
 *
 * `null` matters more here than anywhere else on the screen. The boxes fall back to the
 * loaded airport's own position while they are empty, and until the airport search answers
 * — in flight right after Load, forever if it errors — there is no fallback either. Filling
 * that hole with a zero would stage `(0, 0)`, the server would happily preview a placement
 * in the Gulf of Guinea, and one click would put the aeroplane there. A missing coordinate
 * is "nothing to place", exactly as the Airwork tab already treats a missing airport.
 *
 * The altitude is not held to the same bar: at a coordinate that resolved, an unknown
 * altitude falls back to the airport's elevation and then to sea level, which is a real
 * place the rail prints in full. A wrong altitude is visible and recoverable; a wrong
 * coordinate is 5,000 km of ocean.
 */
function customPlacement(
  custom: {
    readonly latitude: number | null;
    readonly longitude: number | null;
    readonly altitudeFt: number | null;
    readonly headingDeg: number | null;
  },
  fallbacks: {
    readonly airportLatitude: number | null;
    readonly airportLongitude: number | null;
    readonly airportElevationFt: number | null;
    readonly runwayCourse: number | null;
  },
): PlacementInputs['custom'] {
  const latitude = custom.latitude ?? fallbacks.airportLatitude;
  const longitude = custom.longitude ?? fallbacks.airportLongitude;
  if (latitude === null || longitude === null) {
    return null;
  }
  return {
    position: {
      latitude,
      longitude,
      altitude_ft: custom.altitudeFt ?? fallbacks.airportElevationFt ?? 0,
    },
    headingDeg: custom.headingDeg ?? fallbacks.runwayCourse,
  };
}

/** The placement the current screen state means, rebuilt only when an input changes. */
function usePlacementRequest(): PlacementRequest | null {
  const design = useAppSelector((state) => state.positionDesign);
  const { airport } = useAirport();
  const runway = useSelectedRunway();

  const airportLatitude = airport?.position.latitude ?? null;
  const airportLongitude = airport?.position.longitude ?? null;
  const airportElevationFt = airport?.elevation_ft ?? null;
  const runwayCourse = runway?.true_bearing_deg ?? null;
  const {
    loadedIcao,
    selectedRunway,
    selectedStand,
    activeTab,
    selectedMarker,
    finalPlacement,
    circuitDistanceNm,
    procedure,
    procedureFamily,
    airworkLevel,
    custom,
  } = design;

  return useMemo(
    () =>
      buildPlacementRequest({
        icao: loadedIcao,
        runwayIdent: selectedRunway,
        standName: selectedStand,
        activeTab,
        marker: selectedMarker,
        finalPlacement,
        circuitDistanceNm,
        procedure:
          procedure === null
            ? null
            : {
                kind: procedureKindOf(procedureFamily),
                ident: procedure.ident,
                transition: procedure.transition,
                sequence: procedure.sequence,
              },
        airwork:
          airportLatitude !== null && airportLongitude !== null
            ? {
                position: {
                  latitude: airportLatitude,
                  longitude: airportLongitude,
                  altitude_ft: AIRWORK_LEVEL_FEET[airworkLevel],
                },
                headingDeg: runwayCourse ?? 0,
              }
            : null,
        custom: customPlacement(custom, {
          airportLatitude,
          airportLongitude,
          airportElevationFt,
          runwayCourse,
        }),
      }),
    [
      loadedIcao,
      selectedRunway,
      selectedStand,
      activeTab,
      selectedMarker,
      finalPlacement,
      circuitDistanceNm,
      procedure,
      procedureFamily,
      airworkLevel,
      custom,
      airportLatitude,
      airportLongitude,
      airportElevationFt,
      runwayCourse,
    ],
  );
}

export interface StagedPlacement {
  readonly request: PlacementRequest | null;
  readonly preview: PlacementPreview | undefined;
  readonly isFetching: boolean;
  readonly isError: boolean;
  readonly error: unknown;
  readonly setup: InstructorSetup;
  /** The preview's setup with the instructor's edits merged over it, as apply will. */
  readonly merged: ReturnType<typeof mergedSetup>;
}

/**
 * The whole staged placement: the request, the server's answer to it, and what will be
 * applied once the instructor's edits are merged in.
 *
 * Preview is a `query` despite being a POST — it is side-effect-free by design, which is
 * what lets every consumer of this hook share one cached answer.
 */
export function useStagedPlacement(): StagedPlacement {
  const request = usePlacementRequest();
  const config = useAppSelector((state) => state.positionDesign.config);
  const send = useAppSelector((state) => state.positionDesign.send);
  const runway = useSelectedRunway();
  const { ils } = useIls(runway?.ident ?? null);

  const {
    data: preview,
    isFetching,
    isError,
    error,
  } = usePreviewPlacementQuery(request ?? ({} as PlacementRequest), {
    skip: request === null,
  });

  // Memoised so `overrides` is reference-stable: `BottomBar`'s mirror onto `positionSlice`
  // is an effect keyed on it, and a fresh object every render would re-stage forever.
  const setup = useMemo(() => instructorSetup(config, send, ils), [config, send, ils]);
  const merged = useMemo(
    () => mergedSetup(preview, setup.overrides),
    [preview, setup.overrides],
  );
  return { request, preview, isFetching, isError, error, setup, merged };
}
