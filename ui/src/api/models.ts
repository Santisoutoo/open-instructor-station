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

import type { components, operations } from './schema';

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
// Weather Manager
// ---------------------------------------------------------------------------

/** One wind stratum. Direction is TRUE degrees the wind blows FROM, altitude MSL. */
export type WindLayer = components['schemas']['WindLayer'];

/** One cloud stratum. Base and tops are MSL; coverage is a 0-1 ratio, not octas. */
export type CloudLayer = components['schemas']['CloudLayer'];

/** The closed set of cloud types the adapter can render. */
export type CloudType = CloudLayer['cloud_type'];

/** The commanded weather, fully populated — `GET /api/weather`. */
export type WeatherState = components['schemas']['WeatherState'];

/** Surface state for friction, shared by {@link WeatherState} and {@link WeatherSetup}. */
export type RunwayContamination = WeatherState['runway_contamination'];

/** The sparse write model: `null`/absent means "leave that aspect untouched". */
export type WeatherSetup = components['schemas']['WeatherSetup'];

/** The closed set of preset ids the manifest and the request both use. */
export type WeatherPresetId = components['schemas']['WeatherPresetInfo']['id'];

/** One catalogue entry, as `GET /api/weather/manifest` publishes it. */
export type WeatherPresetInfo = components['schemas']['WeatherPresetInfo'];

/** `GET /api/weather/manifest` — supported-or-not with a reason, plus the preset catalogue. */
export type WeatherManifest = components['schemas']['WeatherManifest'];

/** One weather instruction: a preset, an explicit setup, or a preset with overrides. */
export type WeatherRequest = components['schemas']['WeatherRequest'];

/** What `POST /api/weather/apply` would write, resolved without touching the simulator. */
export type WeatherPreview = components['schemas']['WeatherPreview'];

/** What `POST /api/weather/apply` returns: the echo of the write plus the read-back state. */
export type WeatherApplyResult = components['schemas']['WeatherApplyResult'];

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

// ---------------------------------------------------------------------------
// Failures Manager
// ---------------------------------------------------------------------------

/** `GET /api/failures/catalogue` — the catalogue merged with the adapter's support manifest. */
export type FailureCatalogueResponse = components['schemas']['FailureCatalogueResponse'];

/** One catalogue entry, resolved against the active adapter — `supported` gates the row. */
export type FailureCatalogueEntry = components['schemas']['FailureCatalogueEntry'];

/** The closed set of dotted failure ids (`engine.fire`, `instruments.pitot`, …). */
export type FailureId = FailureCatalogueEntry['failure_id'];

export type FailureCategory = FailureCatalogueEntry['category'];

/** `GET /api/failures/status` — active failures (sim truth) plus armed ones (the scheduler). */
export type FailuresStatus = components['schemas']['FailuresStatus'];

/** One failure the simulator reports as failed right now. */
export type ActiveFailure = components['schemas']['ActiveFailure'];

/** One failure waiting on its trigger, with its server-assigned id. */
export type ArmedFailure = components['schemas']['ArmedFailure'];

/** The five-arm trigger union (D6): altitude/speed above-or-below, plus delay. */
export type FailureTrigger = components['schemas']['ArmFailureRequest']['trigger'];

export type FailureTriggerType = FailureTrigger['type'];

export type AltitudeAboveTrigger = components['schemas']['AltitudeAboveTrigger'];
export type AltitudeBelowTrigger = components['schemas']['AltitudeBelowTrigger'];
export type SpeedAboveTrigger = components['schemas']['SpeedAboveTrigger'];
export type SpeedBelowTrigger = components['schemas']['SpeedBelowTrigger'];
export type DelayTrigger = components['schemas']['DelayTrigger'];

/** The body of `POST /api/failures/inject` and `.../clear` — a failure id plus its engine index. */
export type InjectFailureRequest = components['schemas']['InjectFailureRequest'];
export type ClearFailureRequest = components['schemas']['ClearFailureRequest'];

/** The body of `POST /api/failures/arm`. */
export type ArmFailureRequest = components['schemas']['ArmFailureRequest'];

// ---------------------------------------------------------------------------
// Flight Scenario Generator
// ---------------------------------------------------------------------------

/** One manifest row — `GET /api/scenarios`, `GET /api/scenarios/{id}`. */
export type ScenarioSummary = components['schemas']['ScenarioSummary'];

/** A scenario's full validated document, plus its availability — `GET /api/scenarios/{id}`. */
export type ScenarioDetail = components['schemas']['ScenarioDetail'];

/** Every shipped scenario, whether it can run on the active adapter, and why not. */
export type ScenarioManifest = components['schemas']['ScenarioManifest'];

/** The validated shape of one scenario YAML file, as the server parsed it. */
export type ScenarioDocument = components['schemas']['ScenarioDocument'];

/** The whole run's progress — `GET /api/scenarios/run`, polled while `status === 'running'`. */
export type ScenarioRunStatus = components['schemas']['ScenarioRunStatus'];

/** One declared step's progress. Only the blocks a scenario declares appear. */
export type ScenarioStepStatus = components['schemas']['ScenarioStepStatus'];

/** The fixed execution order: weather -> aircraft_state -> position -> failures -> traffic. */
export type ScenarioStepName = ScenarioStepStatus['name'];

export type ScenarioStepStatusValue = ScenarioStepStatus['status'];

export type ScenarioRunStatusValue = ScenarioRunStatus['status'];

// ---------------------------------------------------------------------------
// Training Profiles
// ---------------------------------------------------------------------------

/** A saved scenario with a name and metadata — `GET/POST/PUT /api/profiles/{id}`. */
export type TrainingProfile = components['schemas']['TrainingProfile'];

/** The body of `POST /api/profiles` and `PUT /api/profiles/{id}`. */
export type TrainingProfileCreate = components['schemas']['TrainingProfileCreate'];

/** One row of `GET /api/profiles`. Cheap: no navdata lookup, no adapter read. */
export type ProfileSummary = components['schemas']['ProfileSummary'];

/** `POST /api/profiles/{id}/apply` — almost always 200; degradation is reported in the body. */
export type ProfileApplyResult = components['schemas']['ProfileApplyResult'];

/** The position + aircraft-state step's outcome, within a {@link ProfileApplyResult}. */
export type ProfilePositionOutcome = components['schemas']['ProfilePositionOutcome'];

/** The weather step's outcome, within a {@link ProfileApplyResult}. */
export type ProfileWeatherOutcome = components['schemas']['ProfileWeatherOutcome'];

/** One failure entry's outcome, within a {@link ProfileApplyResult}. */
export type ProfileFailureOutcome = components['schemas']['ProfileFailureOutcome'];

// ---------------------------------------------------------------------------
// AI Traffic Manager
// ---------------------------------------------------------------------------

/** One live traffic entity — `GET /api/traffic/status` and every `WS /ws/traffic` frame. */
export type TrafficContact = components['schemas']['TrafficContact'];

/** The three spawnable kinds: aircraft, ground vehicle, bird. */
export type TrafficKind = TrafficContact['kind'];

/** Which scenario shape a track was built for — a display label, never branched on. */
export type TrafficScenarioShape = TrafficContact['scenario_shape'];

/** One timed point on a traffic entity's path. `t_offset_s` is seconds after spawn. */
export type TrafficWaypoint = components['schemas']['TrafficWaypoint'];

/** A complete, timed path for one entity — what the bridge is handed. */
export type TrafficTrack = components['schemas']['TrafficTrack'];

/** `GET /api/traffic/status`, and the body of every despawn/clear response. */
export type TrafficStatus = components['schemas']['TrafficStatus'];

/** `POST /api/traffic/spawn` — one contact per track the request resolved into. */
export type TrafficSpawnResult = components['schemas']['TrafficSpawnResult'];

/** Converge an intruder on the user aircraft's own projected track. */
export type TcasConflictSpawnRequest =
  components['schemas']['TcasConflictSpawnRequest'];

/** The three named TCAS presets. */
export type TcasSeverity = TcasConflictSpawnRequest['severity'];

/** A vehicle or aircraft crossing the runway, timed to the user's own closing speed. */
export type RunwayIncursionSpawnRequest =
  components['schemas']['RunwayIncursionSpawnRequest'];

/** `n` aircraft on the same final, at named distances. */
export type ApproachSequenceSpawnRequest =
  components['schemas']['ApproachSequenceSpawnRequest'];

/**
 * ICAO approach category as the traffic spawn form needs it.
 *
 * {@link ApproachCategory} comes off an optional position-request field and is therefore
 * nullable; this one is the same closed set without the `null`, because the traffic
 * request defaults it server-side.
 */
export type TrafficApproachCategory = ApproachSequenceSpawnRequest['category'];

/** A traffic entity ground-taxiing an explicit route. */
export type TaxiTrafficSpawnRequest =
  components['schemas']['TaxiTrafficSpawnRequest'];

/** The escape hatch: a hand-built track, e.g. authored from map clicks. */
export type CustomTrackSpawnRequest =
  components['schemas']['CustomTrackSpawnRequest'];

/**
 * The discriminated union `POST /api/traffic/spawn` takes.
 *
 * Read off the operation's own request body rather than spelled out member by member, so
 * a spawn shape added on the server arrives here without an edit — and a `switch` on
 * `type` stops compiling until the panel handles it.
 */
export type TrafficSpawnRequest =
  operations['spawn_traffic_api_traffic_spawn_post']['requestBody']['content']['application/json'];

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

/** Numeric members of {@link TrafficContact}, used by the `/ws/traffic` payload guard. */
const NUMERIC_CONTACT_FIELDS = [
  'latitude',
  'longitude',
  'altitude_ft',
  'heading_deg',
  'ground_speed_kt',
  'vertical_speed_fpm',
] as const satisfies ReadonlyArray<keyof TrafficContact>;

/** String members of {@link TrafficContact} the panel renders or keys on. */
const STRING_CONTACT_FIELDS = [
  'traffic_id',
  'kind',
  'scenario_shape',
  'callsign',
  'label',
] as const satisfies ReadonlyArray<keyof TrafficContact>;

function isTrafficContact(value: unknown): value is TrafficContact {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  if (typeof candidate['on_ground'] !== 'boolean') {
    return false;
  }
  if (STRING_CONTACT_FIELDS.some((field) => typeof candidate[field] !== 'string')) {
    return false;
  }
  return NUMERIC_CONTACT_FIELDS.every((field) => {
    const raw = candidate[field];
    return typeof raw === 'number' && Number.isFinite(raw);
  });
}

/**
 * Runtime guard for `WS /ws/traffic` frames — the same reasoning as
 * {@link isAircraftState}, applied to a list instead of a singleton.
 *
 * A frame is accepted whole or dropped whole: half a contact list is a worse picture of
 * the sky than the previous frame, which the slice keeps until a good one replaces it.
 * An empty array is valid and meaningful — it is exactly what an adapter without
 * `can_spawn_traffic` streams.
 */
export function isTrafficContactList(value: unknown): value is TrafficContact[] {
  return Array.isArray(value) && value.every(isTrafficContact);
}
