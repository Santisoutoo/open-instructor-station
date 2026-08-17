/**
 * The API surface, named.
 *
 * Every type here is an **alias into `schema.d.ts`**, which `npm run generate:api`
 * writes from FastAPI's OpenAPI document. Nothing in this file describes the shape of a
 * payload — it only gives the generated shapes short names, so the rest of the app never
 * has to spell `components['schemas'][…]` and a backend change surfaces as a TypeScript
 * error rather than as a runtime surprise (CLAUDE.md: never hand-write API types).
 *
 * The one piece of real code here is {@link isAircraftState}, and it earns its place: a
 * compile-time type says nothing about what actually arrives over a WebSocket.
 */

import type { components } from './schema';

/** Live aircraft state: `GET /api/state` and every `WS /ws/state` frame. */
export type AircraftState = components['schemas']['AircraftState'];

/** `GET /api/health` */
export type HealthResponse = components['schemas']['HealthResponse'];

/** `GET /api/capabilities` — what the active adapter declares it can do. */
export type Capabilities = components['schemas']['Capabilities'];

export type CapabilityKey = keyof Capabilities;

/** The "configure the aircraft" payload posted to `POST /api/aircraft/setup`. */
export type AircraftSetup = components['schemas']['AircraftSetup'];

/** Exterior light switches. `null`/absent means "leave this switch alone". */
export type LightsSetup = components['schemas']['LightsSetup'];

/** What `POST /api/aircraft/setup` returns: the echo of the write plus the new state. */
export type AircraftSetupResult = components['schemas']['AircraftSetupResult'];

/** One row of `GET /api/aircraft/controls`. */
export type AircraftControlSupport = components['schemas']['AircraftControlSupport'];

/** `GET /api/aircraft/controls` */
export type AircraftControlManifest = components['schemas']['AircraftControlManifest'];

/**
 * The closed set of Aircraft Control panel controls.
 *
 * This is a union rather than `string` because the server declares it as one: the
 * identifiers come straight out of the OpenAPI enum, so the panel's display table cannot
 * name a control the server does not serve, and a control added on the server fails the
 * typecheck here until the panel handles it.
 */
export type ControlId = AircraftControlSupport['control'];

// ---------------------------------------------------------------------------
// Position Manager
// ---------------------------------------------------------------------------

/** `GET /api/navdata/status` — the gate the whole Position panel reads first. */
export type NavdataStatus = components['schemas']['NavdataStatus'];

/** One frame of index-build progress. Present only while `state === 'building'`. */
export type IndexProgress = components['schemas']['IndexProgress'];

/** One row of the airport search. */
export type AirportSummary = components['schemas']['AirportSummary'];

/** One airport in full. */
export type Airport = components['schemas']['Airport'];

/** One runway **end** — 18L and 36R are two of these. */
export type Runway = components['schemas']['Runway'];

/** The ILS serving one runway end. */
export type Ils = components['schemas']['Ils'];

/** A gate, stand, tie-down or hangar. */
export type ParkingStand = components['schemas']['ParkingStand'];

export type ParkingKind = ParkingStand['kind'];

/** Enough of a procedure to list it without parsing its legs. */
export type ProcedureSummary = components['schemas']['ProcedureSummary'];

/** A procedure with every leg resolved. */
export type Procedure = components['schemas']['Procedure'];

/** One leg. `is_positionable` is computed server-side; the UI never reads ARINC. */
export type ProcedureLeg = components['schemas']['ProcedureLeg'];

export type ProcedureKind = ProcedureSummary['kind'];

/** A published holding pattern. */
export type Hold = components['schemas']['Hold'];

/** A point on the WGS84 ellipsoid. */
export type GeoPosition = components['schemas']['GeoPosition'];

/** A resolved placement: where, facing where, at what speed. */
export type Placement = components['schemas']['Placement'];

/**
 * What the instructor is about to do, computed without touching the simulator.
 * The staging bar renders `notes` verbatim — they say where each number came from.
 */
export type PlacementPreview = components['schemas']['PlacementPreview'];

/** Everything the staging bar's SVG needs. */
export type PlacementSchematic = components['schemas']['PlacementSchematic'];

/** One point of that diagram, already projected into the runway's frame. */
export type SchematicPoint = components['schemas']['SchematicPoint'];

/** What actually happened after a commit. */
export type PlacementResult = components['schemas']['PlacementResult'];

/** The body of `POST /api/position/apply`. */
export type ApplyPlacementRequest = components['schemas']['ApplyPlacementRequest'];

/**
 * The discriminated union of everything that can be placed.
 *
 * Taken from the request body of `/api/position/apply` rather than spelled out member by
 * member, so a placement type added on the server arrives here without an edit — and a
 * `switch` on `type` stops compiling until the panel handles it.
 */
export type PlacementRequest = ApplyPlacementRequest['placement'];

/** The named runway-relative placements: the six finals, short final, and eight circuit legs. */
export type RunwayPlacementName =
  components['schemas']['RunwayPlacementRequest']['placement'];

/** ICAO approach category, used to default a speed when the caller states none. */
export type ApproachCategory =
  components['schemas']['RunwayPlacementRequest']['category'];

// ---------------------------------------------------------------------------
// Fuel & Payload Manager
// ---------------------------------------------------------------------------

/** Fuel in one tank — `core.models.TankFuel`. */
export type TankFuel = components['schemas']['TankFuel'];

/** Mass at one payload station — `core.models.PayloadStation`. */
export type PayloadStation = components['schemas']['PayloadStation'];

/** Instructor-facing station classification. The simulator itself does not know it. */
export type StationKind = PayloadStation['kind'];

/** The sparse write model nested on `AircraftSetup.loadout`. `None` means "untouched". */
export type Loadout = components['schemas']['Loadout'];

/** Fully populated fuel and payload, as `get_loadout()` reports it. */
export type LoadoutState = components['schemas']['LoadoutState'];

/** One point of a weight-vs-CG-limit envelope polygon. */
export type CgEnvelopePoint = components['schemas']['CgEnvelopePoint'];

/** The envelope polygon, linearly interpolated between its points. */
export type CgEnvelope = components['schemas']['CgEnvelope'];

/** Static mass/CG facts about the loaded airframe. `None` means genuinely unverifiable. */
export type AirframeMassLimits = components['schemas']['AirframeMassLimits'];

/** The computed mass-and-balance verdict for one loadout. */
export type MassAndBalanceResult = components['schemas']['MassAndBalanceResult'];

/** One preset catalogue entry, as `GET /api/fuel-payload/manifest` lists it. */
export type FuelPayloadPresetInfo = components['schemas']['FuelPayloadPresetInfo'];

/** The closed set of fuel/payload presets: Ferry, Training, Full, Empty. */
export type FuelPayloadPresetId = FuelPayloadPresetInfo['id'];

/** `GET /api/fuel-payload/manifest` — capability, resolved limits, the preset catalogue. */
export type FuelPayloadManifest = components['schemas']['FuelPayloadManifest'];

/** `GET /api/fuel-payload` — the current loadout plus its computed mass-and-balance. */
export type FuelPayloadState = components['schemas']['FuelPayloadState'];

/** The body of `POST /api/fuel-payload/preview` and `/apply` — one shape for both. */
export type FuelPayloadRequest = components['schemas']['FuelPayloadRequest'];

/** What `apply` would produce. Writes nothing. */
export type FuelPayloadPreview = components['schemas']['FuelPayloadPreview'];

/** What actually happened. `state` is the read-back — the honest verdict. */
export type FuelPayloadApplyResult = components['schemas']['FuelPayloadApplyResult'];

/** Numeric members of {@link AircraftState}, used by the runtime WebSocket payload guard. */
const NUMERIC_STATE_FIELDS = [
  'latitude',
  'longitude',
  'altitude_ft',
  'heading_deg',
  'ias_kt',
  'vertical_speed_fpm',
  'pitch_deg',
  'roll_deg',
] as const satisfies ReadonlyArray<keyof AircraftState>;

/**
 * Runtime guard for WebSocket frames. The socket is an untyped byte pipe: a compile-time
 * type says nothing about what actually arrives, so every frame is validated before it
 * reaches the store. A malformed frame is dropped, not rendered as NaN.
 */
export function isAircraftState(value: unknown): value is AircraftState {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  if (typeof candidate['on_ground'] !== 'boolean') {
    return false;
  }
  return NUMERIC_STATE_FIELDS.every((field) => {
    const raw = candidate[field];
    return typeof raw === 'number' && Number.isFinite(raw);
  });
}
