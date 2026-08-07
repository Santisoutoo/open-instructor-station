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
