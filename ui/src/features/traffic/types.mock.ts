/**
 * PROVISIONAL mock-only view models — replace with generated schema.d.ts types at
 * backend integration; never import outside this feature.
 *
 * These mirror `core/traffic.py` as the AI Traffic design (docs/designs/ai-traffic.md §3)
 * specifies it: the entity vocabulary, the timed track, the five spawn-request shapes and
 * the live contact. Once the server track lands and `npm run generate:api` regenerates
 * `schema.d.ts`, the real types replace these aliases and this file dies. Types that the
 * API already serves today (`GeoPosition`) are imported from the generated surface rather
 * than re-spelled — only the not-yet-served shapes are hand-mirrored here.
 */

import type { GeoPosition } from '../../api/models';

/** The three spawnable kinds — design §3.1. */
export type TrafficKind = 'aircraft' | 'ground_vehicle' | 'bird';

/**
 * Which scenario shape a track was built for — carried for display/label purposes only
 * (design §3.1). `custom` is the map's escape hatch, not one of the four spawn forms.
 */
export type TrafficScenarioShape =
  | 'tcas_conflict'
  | 'runway_incursion'
  | 'approach_sequence'
  | 'taxi_traffic'
  | 'custom';

/**
 * ICAO approach category — mirrors `core.geodesy.ApproachCategory`. The generated
 * `ApproachCategory` alias is nullable (it comes off an optional request field), so the
 * non-null closed set is restated here for the picker.
 */
export type TrafficApproachCategory = 'A' | 'B' | 'C' | 'D' | 'E';

/** Named TCAS conflict presets — design §6.1's `TcasSeverity`. */
export type TcasSeverity = 'head_on_ra' | 'crossing_ra' | 'ta_only';

/** One timed point on a traffic entity's path — design §3.2. */
export interface TrafficWaypoint {
  position: GeoPosition;
  /** Ground speed in knots for the leg starting here. */
  speed_kt: number;
  /** True heading at this waypoint, or `null` to derive it from the next leg. */
  heading_deg: number | null;
  /** Seconds after spawn this point is reached. `waypoints[0]` is always 0. */
  t_offset_s: number;
  on_ground: boolean;
}

/** A complete, timed path for one traffic entity — design §3.2. */
export interface TrafficTrack {
  kind: TrafficKind;
  scenario_shape: TrafficScenarioShape;
  /** e.g. `"TFC01"`, `"GND03"`. */
  callsign: string;
  /** Human-readable description, e.g. `"TCAS conflict, head-on"`. */
  label: string;
  waypoints: TrafficWaypoint[];
  /** Seconds after the last waypoint before automatic despawn; `null` holds forever. */
  despawn_after_s: number | null;
}

/** Converge an intruder on the user aircraft's own projected track — design §3.3. */
export interface TcasConflictSpawnRequest {
  type: 'tcas_conflict';
  severity: TcasSeverity;
  /** Intruder's track relative to the user's own: 180 = head-on, 90/270 = crossing. */
  relative_bearing_deg: number;
  miss_side: 'left' | 'right';
  vertical_offset: 'above' | 'below';
  closure_ias_kt: number | null;
  kind: TrafficKind;
  callsign: string;
}

/** A vehicle or aircraft crossing the runway, timed to the user's own closing speed. */
export interface RunwayIncursionSpawnRequest {
  type: 'runway_incursion';
  airport_icao: string;
  runway_ident: string;
  /** NM beyond the threshold, along the landing direction. 0 = the threshold itself. */
  cross_at_along_track_nm: number;
  /** Seconds BEFORE the user's projected arrival that the vehicle starts crossing. */
  lead_time_before_user_arrival_s: number;
  from_side: 'left' | 'right';
  vehicle_speed_kt: number | null;
  kind: TrafficKind;
  callsign: string;
}

/** `n` aircraft on the same final, at named distances — design §3.3. */
export interface ApproachSequenceSpawnRequest {
  type: 'approach_sequence';
  airport_icao: string;
  runway_ident: string;
  distances_nm: number[];
  ias_kt: number | null;
  category: TrafficApproachCategory;
  kind: TrafficKind;
  callsign_prefix: string;
}

/** A traffic entity ground-taxiing an explicit route — design §3.3. */
export interface TaxiTrafficSpawnRequest {
  type: 'taxi_traffic';
  route: GeoPosition[];
  speed_kt: number | null;
  kind: TrafficKind;
  callsign: string;
}

/** The escape hatch: a hand-built track, e.g. authored from map clicks. */
export interface CustomTrackSpawnRequest {
  type: 'custom';
  track: TrafficTrack;
}

/** The discriminated union `POST /api/traffic/spawn` will take — design D7. */
export type TrafficSpawnRequest =
  | TcasConflictSpawnRequest
  | RunwayIncursionSpawnRequest
  | ApproachSequenceSpawnRequest
  | TaxiTrafficSpawnRequest
  | CustomTrackSpawnRequest;

/** One live traffic entity, as every `WS /ws/traffic` frame will report it — design §3.4. */
export interface TrafficContact {
  /** Adapter-assigned uuid4 hex (design D5). Stable for the entity's lifetime. */
  traffic_id: string;
  kind: TrafficKind;
  scenario_shape: TrafficScenarioShape;
  callsign: string;
  label: string;
  latitude: number;
  longitude: number;
  altitude_ft: number;
  heading_deg: number;
  ground_speed_kt: number;
  vertical_speed_fpm: number;
  on_ground: boolean;
}
