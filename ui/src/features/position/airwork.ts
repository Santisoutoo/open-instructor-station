/**
 * The Airwork tab's level ladder — genuinely static UI constants, not navdata.
 *
 * A flight level is a flight level: FL100 is 10,000 ft wherever you are, and the four rungs
 * the screen offers are an editorial choice about which levels a training session uses, not
 * something a navigation database publishes. These lived in the deleted `sampleData.ts`
 * only because that file happened to be where the replica kept its tables; nothing else in
 * it survived the move to real data.
 *
 * The tick widths are pure presentation: the ladder's bars grow with the level so the
 * ladder reads as a ladder at a glance.
 */

import type { AirworkLevel } from './positionDesignSlice';

/** `Record<AirworkLevel, …>` so every rung in the closed set is covered. */
export const AIRWORK_LEVEL_FEET: Record<AirworkLevel, number> = {
  FL300: 30000,
  FL200: 20000,
  FL100: 10000,
  FL050: 5000,
};

/** The ladder tick bar's pixel width, one per level. */
export const AIRWORK_TICK_WIDTH_PX: Record<AirworkLevel, number> = {
  FL300: 58,
  FL200: 44,
  FL100: 30,
  FL050: 18,
};

/** Below this, most training aircraft cannot hold the level — the rail says so. */
export const AIRWORK_MINIMUM_IAS_KT = 150;
