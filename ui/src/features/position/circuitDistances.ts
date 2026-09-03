/**
 * The chip values the circuit-leg distance selectors offer, one set per {@link CircuitLegKind}.
 *
 * Mirrors `finals.ts` one level down: these are free floats sent as `pattern_width_nm` /
 * `leg_distance_nm` (`core/placements.py`), not a named server enum, so there is no generated
 * type to extract them from — the set is this module's own call.
 */

import type { CircuitLegKind } from './positionDesignSlice';

/** The chip values each leg's selector offers, in NM, closest first. */
export const CIRCUIT_LEG_OPTIONS_NM: Record<CircuitLegKind, readonly number[]> = {
  downwind: [2, 3, 4, 5, 6],
  base: [3, 5, 6, 8, 10],
  vectors: [3, 5, 6, 8, 10],
};
