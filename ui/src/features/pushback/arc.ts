/**
 * The pushback arc, computed client-side in the aircraft's local frame — the
 * `map/measure.ts` discipline: pure functions, decorative precision, and anything
 * that must be exact goes through the server's `core.pushback`, never through here.
 *
 * The schematic is drawn relative to the aircraft (a schematic, not a map — the
 * Position Manager's D16 precedent), so a flat local plane replaces geodesy entirely:
 * at the 200 m the request model allows, the flat-earth error is millimetric, far
 * below what a thumbnail can show.
 *
 * Geometry (design §6, D3/D4): the aircraft follows a circular arc of radius
 * `distance_m / radians(angle_deg)` (or a straight line when `angle_deg` is 0),
 * starting tangent to the reciprocal of the current heading. A circular arc's chord
 * bisects the angle between its start and end tangents, so every point comes from the
 * closed-form identity `chord = 2·r·sin(swept/2)` at a bearing of
 * `back_bearing + swept/2` — no numeric integration, the exact formula
 * `core.pushback.pushback_target()` uses.
 */

import type { GeoPosition, PushbackDirection } from '../../api/models';

/** A point in the aircraft's local frame, metres. The aircraft sits at the origin. */
export interface LocalPoint {
  /** Metres to the right of the nose; negative is left. */
  x: number;
  /** Metres ahead of the nose; negative is behind the tail. */
  y: number;
}

/**
 * How many segments the *client-side* schematic draws. Deliberately the same count
 * `core.pushback.PUSHBACK_PATH_PREVIEW_POINTS` uses for its own path, so the thumbnail
 * does not visibly change resolution the moment the server's preview replaces it — but
 * this is a drawing choice, not an API constant, which is why it lives here and not in a
 * hand-typed copy of the schema.
 */
export const PUSHBACK_PATH_PREVIEW_POINTS = 8;

const DEG = Math.PI / 180;

/**
 * Metres per degree of latitude. A sphere is enough here for the same reason the flat
 * plane is: over the ≤200 m a `PushbackRequest` can ask for, the error is millimetric.
 */
const M_PER_DEG_LAT = 111320;

/** `0 · sin(225°)` is `-0`; the origin (and any axis crossing) should read `0`. */
function normalisedZero(value: number): number {
  return value === 0 ? 0 : value;
}

/**
 * D5's sign convention, pinned in one place: `direction` describes where the NOSE
 * ends up — 'right' rotates the final heading clockwise (+), 'left'
 * counter-clockwise (−), 'straight' not at all.
 */
export function signedAngleDeg(direction: PushbackDirection, angleDeg: number): number {
  if (direction === 'right') {
    return angleDeg;
  }
  if (direction === 'left') {
    return -angleDeg;
  }
  return 0;
}

/** The heading the aircraft faces after the manoeuvre, normalised to [0, 360). */
export function finalHeadingDeg(
  headingDeg: number,
  direction: PushbackDirection,
  angleDeg: number,
): number {
  const sum = headingDeg + signedAngleDeg(direction, angleDeg);
  return ((sum % 360) + 360) % 360;
}

/**
 * `points + 1` positions along the manoeuvre, the origin (the aircraft) first and the
 * target last — the local-frame twin of `PushbackTarget.path_preview`. Applying the
 * chord identity at a fraction of the full angle keeps every intermediate point on
 * the SAME circle; `direction='straight'` is the degenerate case (collinear, straight
 * back along the tail).
 */
export function pushbackPathLocal(
  direction: PushbackDirection,
  distanceM: number,
  angleDeg: number,
  points: number = PUSHBACK_PATH_PREVIEW_POINTS,
): LocalPoint[] {
  const signed = signedAngleDeg(direction, angleDeg);
  const path: LocalPoint[] = [];
  for (let i = 0; i <= points; i += 1) {
    const fraction = i / points;
    let chordM: number;
    let bearingDeg: number;
    if (signed === 0) {
      chordM = distanceM * fraction;
      bearingDeg = 180;
    } else {
      const radiusM = distanceM / (Math.abs(signed) * DEG);
      const sweptDeg = signed * fraction;
      chordM = 2 * radiusM * Math.sin((Math.abs(sweptDeg) * DEG) / 2);
      bearingDeg = 180 + sweptDeg / 2;
    }
    path.push({
      x: normalisedZero(chordM * Math.sin(bearingDeg * DEG)),
      y: normalisedZero(chordM * Math.cos(bearingDeg * DEG)),
    });
  }
  return path;
}

/**
 * The server's own `PushbackTarget.path_preview`, projected into the same nose-up local
 * frame so the schematic can draw *the server's* answer rather than a client-side
 * re-derivation of it.
 *
 * `origin` is the preview's `current_position` and `headingDeg` its `current_heading_deg`,
 * so the first point lands on the origin and the path runs down the screen behind the
 * aircraft. Altitude is ignored: this is a plan view of a manoeuvre on a ramp.
 */
export function projectPathLocal(
  path: readonly GeoPosition[],
  origin: GeoPosition,
  headingDeg: number,
): LocalPoint[] {
  const mPerDegLon = M_PER_DEG_LAT * Math.cos(origin.latitude * DEG);
  const heading = headingDeg * DEG;
  return path.map((point) => {
    const northM = (point.latitude - origin.latitude) * M_PER_DEG_LAT;
    const eastM = (point.longitude - origin.longitude) * mPerDegLon;
    // Rotate the local ENU offset into the aircraft's frame: +y is the nose.
    return {
      x: normalisedZero(eastM * Math.cos(heading) - northM * Math.sin(heading)),
      y: normalisedZero(eastM * Math.sin(heading) + northM * Math.cos(heading)),
    };
  });
}
