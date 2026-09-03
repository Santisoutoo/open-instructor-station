/**
 * The 9 circuit markers drawn on the Approach training tab's diagram, and where their
 * labels sit relative to the dot.
 *
 * `(u, v)` is **schematic**: along-track and cross-track nautical miles in the diagram's own
 * fixed-scale frame, drawn so an instructor can point at a leg. They are not a position and
 * they never leave this screen — `placementRequest.ts` turns a marker into a *named* server
 * placement, and `core.geodesy` computes where that actually is.
 *
 * There is deliberately no altitude and no heading here. Both are resolved by the server's
 * preview (a 3° path from the runway's own threshold elevation, a circuit height, the
 * runway's true bearing), and a second, client-side answer to the same question would be a
 * number on screen that the aircraft never gets.
 */

import { place } from './circuit';
import { FINAL_DISTANCE_NM, type FinalPlacementName } from './finals';
import { MARKER_IDS, type CircuitLegKind, type MarkerId } from './positionDesignSlice';

export interface CircuitMarker {
  readonly id: MarkerId;
  readonly label: string;
  /** Along-track NM, negative = before the threshold (on approach). Schematic only. */
  readonly u: number;
  /** Cross-track NM, negative = left of centreline. Schematic only. */
  readonly v: number;
}

/** `Record<MarkerId, …>` — every id in the closed set is covered, checked at compile time. */
export const CIRCUIT_MARKERS: Record<MarkerId, CircuitMarker> = {
  takeoff: { id: 'takeoff', label: 'Take off', u: 0, v: 0 },
  'downwind-left': { id: 'downwind-left', label: 'Downwind left', u: -1, v: -4 },
  'downwind-right': { id: 'downwind-right', label: 'Downwind right', u: -1, v: 4 },
  'vectors-left': { id: 'vectors-left', label: 'Vectors left', u: -6, v: -2 },
  'vectors-right': { id: 'vectors-right', label: 'Vectors right', u: -6, v: 2 },
  'base-left': { id: 'base-left', label: 'Base left', u: -6, v: -4 },
  'base-right': { id: 'base-right', label: 'Base right', u: -6, v: 4 },
  // Generic "Final", not "3 NM final": the dot's label is static, but the distance it places
  // at is whatever the finals chip selector currently has picked — `markerLabel()` (not this
  // field) is what names the actual selected distance, in the tab's heading.
  'final-3nm': { id: 'final-3nm', label: 'Final', u: -6, v: 0 },
  'final-8nm': { id: 'final-8nm', label: '8 NM final', u: -8, v: 0 },
};

/** True for the two markers the final-distance selector drives. */
export function isFinalMarker(id: MarkerId): id is 'final-3nm' | 'final-8nm' {
  return id === 'final-3nm' || id === 'final-8nm';
}

/**
 * `MARKER_IDS` minus the 8 NM final dot/label/button. `final_8nm` stays fully selectable via
 * the finals chip menu (`finals.ts` / `positionDesignSlice.ts`) — only its redundant diagram
 * presence is removed, since the chip menu already covers that distance precisely.
 */
export const DRAWN_MARKER_IDS = MARKER_IDS.filter((id) => id !== 'final-8nm');

/** Every circuit marker id except the threshold and the two finals. */
export type CircuitLegMarkerId = Exclude<MarkerId, 'takeoff' | 'final-3nm' | 'final-8nm'>;

/** Which leg-distance selector drives each circuit marker's request — exhaustive by construction. */
export const MARKER_LEG_KIND: Record<CircuitLegMarkerId, CircuitLegKind> = {
  'downwind-left': 'downwind',
  'downwind-right': 'downwind',
  'base-left': 'base',
  'base-right': 'base',
  'vectors-left': 'vectors',
  'vectors-right': 'vectors',
};

/** Which leg-distance selector a marker's request is driven by; `null` for takeoff and the finals. */
export function legKindOf(id: MarkerId): CircuitLegKind | null {
  if (id === 'takeoff' || isFinalMarker(id)) {
    return null;
  }
  return MARKER_LEG_KIND[id];
}

/**
 * True for the two downwind markers, whose distance is measured **abeam** the threshold and
 * not along the approach — the only pair on the diagram the footnote's "from the threshold"
 * does not describe.
 */
export function isDownwindMarker(id: MarkerId): boolean {
  return id === 'downwind-left' || id === 'downwind-right';
}

/**
 * How far from the threshold this marker places, in NM.
 *
 * The two final markers answer with the tab's selected final rather than with the dot they
 * draw: the diagram keeps its two illustrative dots, the selector is what places. Every other
 * circuit marker answers with its own leg's selected distance; the threshold is zero.
 */
export function markerDistanceNm(
  id: MarkerId,
  final: FinalPlacementName,
  circuitDistanceNm: Record<CircuitLegKind, number>,
): number {
  if (isFinalMarker(id)) {
    return FINAL_DISTANCE_NM[final];
  }
  const legKind = legKindOf(id);
  return legKind === null ? 0 : circuitDistanceNm[legKind];
}

/** The label shown for the selected marker: the finals name their selected distance. */
export function markerLabel(id: MarkerId, final: FinalPlacementName): string {
  if (!isFinalMarker(id)) {
    return CIRCUIT_MARKERS[id].label;
  }
  return final === 'short_final'
    ? 'Short final'
    : `${String(FINAL_DISTANCE_NM[final])} NM final`;
}

export type LabelAnchor = 'above' | 'below' | 'left' | 'right';

/**
 * Where a marker's label sits relative to its dot. `takeoff`, `final-3nm` and the two
 * `vectors-*` markers use the fixed unit vectors the source gives them; every other marker
 * derives its unit vector from its own screen position relative to the diagram centre.
 * `vectors-left`/`vectors-right` are always centred below, per the source — not run through
 * the `|ux| > 0.6` test the other markers use.
 */
export function labelPlacement(id: MarkerId, courseDeg: number): LabelAnchor {
  if (id === 'vectors-left' || id === 'vectors-right') {
    return 'below';
  }

  const rad = (courseDeg * Math.PI) / 180;
  let ux: number;
  let uy: number;
  if (id === 'takeoff') {
    ux = Math.cos(rad);
    uy = Math.sin(rad);
  } else if (id === 'final-3nm') {
    ux = -Math.cos(rad);
    uy = -Math.sin(rad);
  } else {
    const marker = CIRCUIT_MARKERS[id];
    const centre = place(0, 0, courseDeg);
    const point = place(marker.u, marker.v, courseDeg);
    const dx = point.x - centre.x;
    const dy = point.y - centre.y;
    const length = Math.hypot(dx, dy) || 1;
    ux = dx / length;
    uy = dy / length;
  }

  if (Math.abs(ux) > 0.6) {
    return ux > 0 ? 'right' : 'left';
  }
  return uy > 0 ? 'below' : 'above';
}
