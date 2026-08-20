/**
 * Whether a placement is flying, and how fast it has to be going to keep doing it.
 *
 * This exists because of the failure CLAUDE.md's placement-speed note records: an aircraft
 * put on a perfect 10 NM final at 0 kt is in the terrain a few seconds later, and it cost
 * four days to find. `core.geodesy.coordinate_placement` defaults to `GROUND_IAS_KT` — zero,
 * profile `"ground"` — because a bare coordinate is as likely a parking spot as a cruise
 * level, and its own docstring says an airborne caller must state a speed. The two coordinate
 * placements this screen sends (Airwork, Custom location) carry no `ias_kt`, so **every one
 * of them resolves to 0 kt**. At FL100 that is not a placement, it is a crash.
 *
 * The server cannot decide this for us — it has no way of knowing whether the instructor
 * means a cruise level or a hardstand — so the screen has to ask, and refuse to commit until
 * it is answered.
 *
 * Pure arithmetic over the numbers the preview already resolved: no store, no fetch, no
 * geometry. Nothing here re-derives a position.
 */

import { formatAltitudeFt, formatSpeedKt } from './format';

/**
 * Above this height over the ground, a placement is flying.
 *
 * Generous on purpose. A threshold or a stand resolves to within a few feet of field
 * elevation; a circuit is 1,500 ft up. Nothing legitimate sits in between.
 */
export const AIRBORNE_AGL_FT = 500;

/** Below this an aeroplane is not flying at any altitude — this is the 0 kt teleport. */
export const MINIMUM_AIRBORNE_IAS_KT = 60;

/** At and above this altitude the thin air asks for a great deal more. */
export const HIGH_LEVEL_FT = 10_000;

/** What most training aircraft need to hold a flight level. */
export const HIGH_LEVEL_MINIMUM_IAS_KT = 150;

export interface SpeedInputs {
  /** The altitude that will be applied, feet MSL. `null` before the preview answers. */
  readonly altitudeFt: number | null;
  /** Field elevation under the placement, feet MSL. `null` falls back to sea level. */
  readonly groundElevationFt: number | null;
  /** The speed that will be applied, knots. `null` before the preview answers. */
  readonly iasKt: number | null;
}

/** Whether the placement puts the aircraft in the air. Unknown altitude counts as ground. */
export function isAirborne(inputs: SpeedInputs): boolean {
  if (inputs.altitudeFt === null) {
    return false;
  }
  return inputs.altitudeFt - (inputs.groundElevationFt ?? 0) >= AIRBORNE_AGL_FT;
}

/** The slowest speed worth arriving at that altitude with, knots. */
export function sustainableIasKt(altitudeFt: number): number {
  return altitudeFt >= HIGH_LEVEL_FT
    ? HIGH_LEVEL_MINIMUM_IAS_KT
    : MINIMUM_AIRBORNE_IAS_KT;
}

/**
 * Why the placement cannot be committed as it stands, or `null` when it can.
 *
 * Deliberately narrower than the rail's caution: a slow placement at a flight level is worth
 * *saying*, but a speed below {@link MINIMUM_AIRBORNE_IAS_KT} in the air is worth *refusing*,
 * because there is no aircraft and no instructor intent it could be right for. The instructor
 * clears it by stating an IAS in the bottom bar, which is the same field the apply endpoint
 * carries through to both `apply_setup` and `set_position`.
 */
export function unflyableReason(inputs: SpeedInputs): string | null {
  if (!isAirborne(inputs) || inputs.altitudeFt === null || inputs.iasKt === null) {
    return null;
  }
  if (inputs.iasKt >= MINIMUM_AIRBORNE_IAS_KT) {
    return null;
  }
  return (
    `This placement is airborne at ${formatAltitudeFt(inputs.altitudeFt)} and would ` +
    `arrive at ${formatSpeedKt(inputs.iasKt)}. State an IAS of at least ` +
    `${formatSpeedKt(MINIMUM_AIRBORNE_IAS_KT)} before placing.`
  );
}
