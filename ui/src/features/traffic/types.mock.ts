/**
 * PROVISIONAL mock-only view models — replace with generated schema.d.ts types at
 * backend integration; never import outside this feature.
 *
 * These describe what the traffic bridge *will* serve. Once the FastAPI endpoints and
 * the bridge exist, `npm run generate:api` produces the real types and this file dies.
 */

/** The three spawnable kinds from feature-spec §13. */
export type TrafficKind = 'aircraft' | 'ground vehicle' | 'birds';

export interface LatLon {
  lat: number;
  lon: number;
}

/** One live AI entity, as the bridge would report it. */
export interface TrafficEntity {
  id: string;
  /** Mono-styled identifier, e.g. `IBE3421` for aircraft or `FOL12` for a follow-me. */
  callsign: string;
  kind: TrafficKind;
  position: LatLon;
  altitude_ft: number;
  /** True heading in degrees, 0–360. */
  heading_deg: number;
  /** Ground speed in knots. */
  speed_kt: number;
  /**
   * Remaining waypoints the entity advances along, in order. When the track runs out
   * the entity continues straight on its current heading.
   */
  track: LatLon[];
}

/**
 * Whether the AI traffic manager may be used at all, and why not when it may not.
 *
 * Traffic is the one manager that needs the in-sim bridge plugin (feature-spec §13):
 * `available` mirrors the `can_spawn_traffic` capability the bridge unlocks.
 */
export interface TrafficManifest {
  available: boolean;
  /** Shown to the instructor verbatim when `available` is false. `null` when open. */
  reason: string | null;
  /** Human-readable bridge link state, e.g. `connected (demo)`. */
  bridge: string;
}

/** Every card on the spawn grid: the three kinds plus the four scenario shapes. */
export type SpawnTemplateId =
  | 'aircraft'
  | 'ground-vehicle'
  | 'birds'
  | 'tcas-conflict'
  | 'runway-incursion'
  | 'taxi-traffic'
  | 'approach-traffic';

/** Where the student's aircraft is, for spawning traffic *relative* to it. */
export interface OwnShipRef {
  position: LatLon;
  altitude_ft: number;
  heading_deg: number;
}

/** What a spawn card sends. The template decides how the parameters are used. */
export interface SpawnRequest {
  template: SpawnTemplateId;
  /** How many entities, for the plain-kind templates. Scenarios fix their own count. */
  count: number;
  /** Spawn distance in NM, for the templates where distance is meaningful. */
  distanceNm: number;
  /** Own aircraft, or `null` before telemetry — then the fallback field is used. */
  own: OwnShipRef | null;
}
