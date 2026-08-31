/**
 * A small, real-shaped world for the Position screen's component tests.
 *
 * Two runway ends at LFMN, one with an ILS and one without, four stands, a wind that gives
 * one end a headwind and the other a tailwind, and a preview whose numbers are the ones the
 * rail is supposed to render. Everything is typed against the **generated** API types, so a
 * server-side model change breaks these fixtures at compile time instead of leaving the
 * suite green against a shape that no longer exists.
 *
 * Named without `.test.` so Vitest does not try to run it as a suite.
 */

import type {
  AirportSummary,
  Capabilities,
  Ils,
  NavdataStatus,
  ParkingStand,
  PlacementPreview,
  PlacementResult,
  Procedure,
  ProcedureSummary,
  Runway,
  WeatherState,
} from '../../api/models';
import type { Answer } from './testApi';

export const ICAO = 'LFMN';

export const AIRPORT: AirportSummary = {
  icao: ICAO,
  iata: 'NCE',
  name: "Nice / Côte d'Azur",
  position: { latitude: 43.6584, longitude: 7.2159, altitude_ft: 12 },
  elevation_ft: 12,
  longest_runway_m: 2960,
  has_procedures: true,
};

export const ILS_04R: Ils = {
  airport_icao: ICAO,
  runway_ident: '04R',
  localizer_ident: 'NR',
  frequency_khz: 110700,
  localizer_position: { latitude: 43.6675, longitude: 7.2276, altitude_ft: 12 },
  localizer_true_deg: 42.7,
  localizer_mag_deg: 40,
  glideslope_deg: 3,
  has_dme: true,
};

export const RUNWAY_04R: Runway = {
  airport_icao: ICAO,
  ident: '04R',
  threshold: { latitude: 43.6549, longitude: 7.2033, altitude_ft: 12 },
  true_bearing_deg: 40,
  length_m: 2960,
  elevation_ft: 12,
  displaced_threshold_m: 0,
  opposite_ident: '22L',
  surface: 'asphalt',
  ils: ILS_04R,
};

export const RUNWAY_22L: Runway = {
  airport_icao: ICAO,
  ident: '22L',
  threshold: { latitude: 43.6752, longitude: 7.2293, altitude_ft: 12 },
  true_bearing_deg: 220,
  length_m: 2960,
  elevation_ft: 12,
  displaced_threshold_m: 0,
  opposite_ident: '04R',
  surface: 'asphalt',
  ils: null,
};

export const RUNWAYS: readonly Runway[] = [RUNWAY_04R, RUNWAY_22L];

function stand(
  name: string,
  kind: ParkingStand['kind'],
  latitude: number,
  longitude: number,
): ParkingStand {
  return {
    airport_icao: ICAO,
    name,
    position: { latitude, longitude, altitude_ft: 12 },
    heading_true_deg: 90,
    kind,
    aircraft_types: [],
    airline_codes: [],
  };
}

export const STANDS: readonly ParkingStand[] = [
  stand('A1', 'gate', 43.6602, 7.2101),
  stand('A2', 'gate', 43.6604, 7.2106),
  stand('T1', 'tie_down', 43.6588, 7.2085),
  stand('H1', 'hangar', 43.6577, 7.2073),
];

/** 240°/12 kt: an 11 kt tailwind on 04R and an 11 kt headwind on 22L. */
function approach(
  ident: string,
  approach_type: NonNullable<ProcedureSummary['approach_type']> | null,
  transition: string | null = null,
): ProcedureSummary {
  return {
    airport_icao: ICAO,
    kind: 'approach',
    ident,
    transition,
    runway_idents: ['04R'],
    approach_type,
    leg_count: 3,
    positionable_leg_count: 2,
  };
}

/**
 * The procedures LFMN "publishes" here: one SID, and approaches to 04R of three real types
 * plus one the provider could not classify — enough for the type filter to have something
 * to hide. Not in `positionRoutes()` by default: most screens want an empty list.
 */
export const PROCEDURES: readonly ProcedureSummary[] = [
  {
    airport_icao: ICAO,
    kind: 'sid',
    ident: 'BADO8A',
    transition: null,
    runway_idents: ['04R'],
    approach_type: null,
    leg_count: 4,
    positionable_leg_count: 3,
  },
  approach('I04R', 'ils'),
  // A named transition really arrives as "unknown" (its ARINC route type says only
  // "transition"); the UI shows it as ILS by inheriting the common route's type.
  approach('I04R', 'unknown', 'MUS'),
  approach('R04R', 'rnav'),
  approach('V04R', 'vor'),
  approach('X04R', null),
];

const LEG_FLAGS = {
  is_flyover: false,
  is_initial_approach_fix: false,
  is_final_approach_fix: false,
  is_missed_approach_point: false,
  is_missed_approach_leg: false,
  is_end_of_procedure: false,
} as const;

/** The ILS 04R common route, with the climb-out `CA` the server refuses to place on. */
export const PROCEDURE_I04R: Procedure = {
  airport_icao: ICAO,
  kind: 'approach',
  ident: 'I04R',
  transition: null,
  runway_idents: ['04R'],
  approach_type: 'ils',
  legs: [
    {
      ...LEG_FLAGS,
      sequence: 10,
      path_terminator: 'IF',
      is_positionable: true,
      fix: {
        ident: 'NERAS',
        kind: 'fix',
        position: { latitude: 43.5, longitude: 7.0, altitude_ft: 0 },
      },
      altitude: {
        descriptor: '+',
        min_ft: 3000,
        min_is_flight_level: false,
        max_is_flight_level: false,
        display: 'at or above 3000 ft',
      },
    },
    {
      ...LEG_FLAGS,
      sequence: 20,
      path_terminator: 'CF',
      is_positionable: true,
      fix: {
        ident: 'RW04R',
        kind: 'runway',
        position: { latitude: 43.6584, longitude: 7.2159, altitude_ft: 12 },
      },
    },
    {
      ...LEG_FLAGS,
      sequence: 30,
      path_terminator: 'CA',
      is_missed_approach_leg: true,
      is_positionable: false,
      unpositionable_reason: 'A CA leg carries no defensible coordinate.',
    },
  ],
};

export const WEATHER: WeatherState = {
  wind_layers: [
    {
      altitude_ft: 0,
      direction_deg: 240,
      speed_kt: 12,
      gust_increase_kt: 0,
      turbulence_ratio: 0,
    },
  ],
  cloud_layers: [],
  visibility_m: 9999,
  qnh_hpa: 1013,
  temperature_c: 26,
  dewpoint_c: 18,
  precipitation_ratio: 0,
  runway_contamination: 'dry',
};

export const CAPABILITIES: Capabilities = {
  can_set_position: true,
  can_set_aircraft_state: true,
  can_set_weather: true,
  can_inject_failures: true,
  can_spawn_traffic: false,
  can_control_autopilot: true,
  can_set_fuel_payload: true,
  can_control_camera: false,
  can_pushback: false,
};

export const NAVDATA_READY: NavdataStatus = {
  state: 'ready',
  provider: 'in_memory',
  airac_cycle: '2508',
};

export const PREVIEW: PlacementPreview = {
  request: {
    type: 'runway',
    airport_icao: ICAO,
    runway_ident: '04R',
    placement: 'final_3nm',
  },
  placement: {
    position: { latitude: 43.62, longitude: 7.17, altitude_ft: 968 },
    heading_deg: 40,
    ias_kt: 121,
    label: 'LFMN 04R 3 NM final',
    profile: 'final',
    ils: ILS_04R,
    glideslope_deg: 3,
  },
  setup: {
    altitude_ft: 968,
    heading_deg: 40,
    ias_kt: 121,
    gear_down: true,
    flaps_ratio: 0.5,
    nav1_freq_khz: 110700,
    obs1_deg: 40,
  },
  schematic: { runway_ident: '04R', points: [] },
  notes: ['Altitude from a 3.0° glidepath, 3.0 NM from the threshold.'],
};

/**
 * What a coordinate placement really comes back as when the caller states no speed.
 *
 * `core.geodesy.coordinate_placement` defaults to `GROUND_IAS_KT` — 0 kt, profile
 * `"ground"` — whatever altitude it is handed, so FL100 overhead the field resolves
 * stationary. This is not a contrived fixture: it is what both of this screen's coordinate
 * tabs get today, and it is the placement the commit gate exists to refuse.
 */
export const AIRBORNE_PREVIEW: PlacementPreview = {
  request: {
    type: 'coordinate',
    position: { latitude: 43.6584, longitude: 7.2159, altitude_ft: 10000 },
    heading_deg: 40,
  },
  placement: {
    position: { latitude: 43.6584, longitude: 7.2159, altitude_ft: 10000 },
    heading_deg: 40,
    ias_kt: 0,
    label: 'Coordinate 43.6584 / 7.2159',
    profile: 'ground',
    ils: null,
    glideslope_deg: null,
  },
  setup: { altitude_ft: 10000, heading_deg: 40, ias_kt: 0 },
  schematic: { points: [] },
  notes: ['No speed was requested, so the placement is stationary.'],
};

export const APPLY_RESULT: PlacementResult = {
  placement: PREVIEW.placement,
  applied: PREVIEW.setup,
  state: {
    latitude: 43.62,
    longitude: 7.17,
    altitude_ft: 968,
    heading_deg: 40,
    ias_kt: 121,
    vertical_speed_fpm: -650,
    pitch_deg: 0,
    roll_deg: 0,
    on_ground: false,
  },
};

/**
 * The route table for `stubApi`.
 *
 * Order matters: `stubApi` returns the first fragment that matches, so every specific
 * `navdata/airports/…` route is declared before the bare airport search.
 */
export function positionRoutes(
  overrides: Record<string, Answer> = {},
): Record<string, Answer> {
  return {
    'navdata/status': { body: NAVDATA_READY },
    'runways/04R/ils': { body: ILS_04R },
    'runways/22L/ils': { status: 404, detail: 'No ILS on 22L' },
    [`airports/${ICAO}/runways`]: { body: RUNWAYS },
    [`airports/${ICAO}/parking`]: { body: STANDS },
    [`airports/${ICAO}/procedures`]: { body: [] },
    'navdata/airports': { body: [AIRPORT] },
    capabilities: { body: CAPABILITIES },
    'position/preview': { body: PREVIEW },
    'position/apply': { body: APPLY_RESULT },
    weather: { body: WEATHER },
    ...overrides,
  };
}
