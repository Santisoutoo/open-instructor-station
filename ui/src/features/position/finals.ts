/**
 * The server's seven finals, named and ordered for the Approach tab's distance selector.
 *
 * The circuit diagram draws two illustrative final dots (3 NM and 8 NM) because that is
 * what the approved v3 mockup draws. The mockup's fixed markers cannot express the 20 / 15
 * / 10 / 5 NM finals the Position Manager actually serves, so the final marker carries a
 * selector over the whole set — and Phase 1's exit criterion ("a 10 NM ILS final") stops
 * being unreachable from this screen.
 *
 * {@link FinalPlacementName} is **extracted from the generated enum**, never spelled out:
 * `RunwayPlacementName` is the union `POST /api/position/preview` accepts, so a final added
 * in `core/geodesy.py` lands here as a missing key in {@link FINAL_LABELS} — a type error
 * at build time rather than a placement the instructor can never reach.
 */

import type { RunwayPlacementName } from '../../api/models';

/** The finals half of the server's runway-placement enum. */
export type FinalPlacementName = Extract<
  RunwayPlacementName,
  `final_${string}` | 'short_final'
>;

/**
 * Every final the server serves, with the label the selector shows.
 *
 * A `Record` over the extracted union, so this is exhaustive by construction.
 */
export const FINAL_LABELS: Record<FinalPlacementName, string> = {
  final_20nm: '20 NM',
  final_15nm: '15 NM',
  final_10nm: '10 NM',
  final_8nm: '8 NM',
  final_5nm: '5 NM',
  final_3nm: '3 NM',
  short_final: 'Short',
};

/**
 * Distance from the threshold, in nautical miles.
 *
 * Display only — it labels the selector and the "Distance" fact. The position itself is
 * always the server's: the request carries the placement's *name*, never a distance.
 * `short_final` is `core.geodesy.SHORT_FINAL_DISTANCE_NM`.
 */
export const FINAL_DISTANCE_NM: Record<FinalPlacementName, number> = {
  final_20nm: 20,
  final_15nm: 15,
  final_10nm: 10,
  final_8nm: 8,
  final_5nm: 5,
  final_3nm: 3,
  short_final: 1,
};

/** Longest first — the order an approach is flown. */
export const FINAL_ORDER = [
  'final_20nm',
  'final_15nm',
  'final_10nm',
  'final_8nm',
  'final_5nm',
  'final_3nm',
  'short_final',
] as const satisfies readonly FinalPlacementName[];

/** What the selector starts on: the 3 NM final the mockup's default marker draws. */
export const DEFAULT_FINAL: FinalPlacementName = 'final_3nm';
