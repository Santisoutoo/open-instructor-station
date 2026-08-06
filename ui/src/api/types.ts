/**
 * ============================================================================
 * TODO(phase-0): PLACEHOLDER — DELETE THIS FILE ONCE THE BACKEND IS UP.
 * ============================================================================
 *
 * CLAUDE.md rule: "the UI client is generated from FastAPI's OpenAPI schema.
 * **Never hand-write API types** in the frontend."
 *
 * These types are hand-written *only* because the FastAPI server is being built in
 * parallel and `http://localhost:8000/openapi.json` is not reachable yet, so
 * `npm run generate:api` cannot run. They mirror the Phase-0 contract agreed with the
 * backend agent, nothing more.
 *
 * Replacement procedure, as soon as the server responds on :8000:
 *   1. `npm run generate:api`            -> writes src/api/schema.d.ts
 *   2. Re-point src/api/instructorApi.ts at the generated schema, e.g.
 *        import type { components } from './schema';
 *        type AircraftState = components['schemas']['AircraftState'];
 *   3. Delete this file.
 *
 * See ui/README.md ("Generated API types") for the full caveat.
 * ============================================================================
 */

/** Live aircraft state, pushed over `WS /ws/state` at ~4 Hz and served by `GET /api/state`. */
export interface AircraftState {
  latitude: number;
  longitude: number;
  altitude_ft: number;
  heading_deg: number;
  ias_kt: number;
  vertical_speed_fpm: number;
  pitch_deg: number;
  roll_deg: number;
  on_ground: boolean;
}

/** `GET /api/health` */
export interface HealthResponse {
  status: string;
  adapter: string;
  connected: boolean;
}

/**
 * `GET /api/capabilities` — every field is a boolean.
 *
 * Hard rule 3 of CLAUDE.md ("capabilities, not failures"): the UI reads these flags and
 * *disables* what the active adapter cannot do. It never calls an unsupported endpoint and
 * lets it throw.
 */
export interface Capabilities {
  can_set_position: boolean;
  can_set_aircraft_state: boolean;
  can_set_weather: boolean;
  can_inject_failures: boolean;
  can_spawn_traffic: boolean;
  can_control_autopilot: boolean;
  can_set_fuel_payload: boolean;
  can_control_camera: boolean;
  can_pushback: boolean;
}

export type CapabilityKey = keyof Capabilities;

/** Display order and human labels for the capability flags. */
export const CAPABILITY_LABELS: ReadonlyArray<readonly [CapabilityKey, string]> = [
  ['can_set_position', 'Set position'],
  ['can_set_aircraft_state', 'Set aircraft state'],
  ['can_set_weather', 'Set weather'],
  ['can_inject_failures', 'Inject failures'],
  ['can_spawn_traffic', 'Spawn traffic'],
  ['can_control_autopilot', 'Control autopilot'],
  ['can_set_fuel_payload', 'Set fuel & payload'],
  ['can_control_camera', 'Control camera'],
  ['can_pushback', 'Pushback'],
];

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
] as const;

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
