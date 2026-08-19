/**
 * PROVISIONAL mock-only view models — replace with generated schema.d.ts types at
 * backend integration; never import outside this feature.
 *
 * These mirror `core/pushback.py` from the design (docs/designs/pushback-manager.md §3).
 * Once the pushback router lands and `npm run generate:api` regenerates
 * `src/api/schema.d.ts`, the real types (and `PushbackDirection` as a closed union from
 * the OpenAPI schema) replace this file and it dies.
 */

import type { GeoPosition } from '../../api/models';

/** D5: `direction` describes where the NOSE ends up, never which way the tail swings. */
export type PushbackDirection = 'straight' | 'left' | 'right';

/** §3 constants, echoed by `GET /api/pushback/manifest` once the backend exists. */
export const PUSHBACK_MAX_DISTANCE_M = 200;
export const PUSHBACK_MAX_ANGLE_DEG = 180;
/** Points along the manoeuvre *in addition to* the origin — 9 points total. */
export const PUSHBACK_PATH_PREVIEW_POINTS = 8;

/**
 * The exact wire shape of one pushback instruction (`POST /preview` and
 * `POST /execute` both take it). `angle_deg` is the TOTAL heading change over the
 * manoeuvre, not a rate — 0 for 'straight', > 0 otherwise.
 */
export interface PushbackRequest {
  direction: PushbackDirection;
  /** Arc length (or straight length) the aircraft travels, metres. 0 < x <= 200. */
  distance_m: number;
  /** Total heading change through the manoeuvre, degrees. 0 <= x <= 180. */
  angle_deg: number;
}

/** The resolved outcome of one request, from a given starting state. */
export interface PushbackTarget {
  position: GeoPosition;
  heading_deg: number;
  /**
   * PUSHBACK_PATH_PREVIEW_POINTS + 1 points along the manoeuvre, current position
   * first and target last. Collinear when direction is 'straight'.
   */
  path_preview: GeoPosition[];
}

/** `POST /api/pushback/preview` response. */
export interface PushbackPreview {
  request: PushbackRequest;
  current_position: GeoPosition;
  current_heading_deg: number;
  target: PushbackTarget;
}

/** `GET /api/pushback/manifest` response. */
export interface PushbackManifest {
  adapter: string;
  supported: boolean;
  /** Shown to the instructor verbatim when `supported` is false. `null` when open. */
  reason: string | null;
  max_distance_m: number;
  max_angle_deg: number;
}
