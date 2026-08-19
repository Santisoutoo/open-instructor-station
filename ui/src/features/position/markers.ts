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
import type { MarkerId } from './positionDesignSlice';

export interface CircuitMarker {
  readonly id: MarkerId;
  readonly label: string;
  /** Along-track NM, negative = before the threshold (on approach). Schematic only. */
  readonly u: number;
  /** Cross-track NM, negative = left of centreline. Schematic only. */
  readonly v: number;
  /**
   * The distance the marker's own request asks for, in NM — 4 NM abeam on downwind, a 6 NM
   * base leg. `null` for the two final markers, whose distance is the tab's final selector,
   * and for the threshold, which is at zero by definition.
   */
  readonly distNm: number | null;
}

/** `Record<MarkerId, …>` — every id in the closed set is covered, checked at compile time. */
export const CIRCUIT_MARKERS: Record<MarkerId, CircuitMarker> = {
  takeoff: { id: 'takeoff', label: 'Take off', u: 0, v: 0, distNm: 0 },
  'downwind-left': {
    id: 'downwind-left',
    label: 'Downwind left',
    u: -1,
    v: -4,
    distNm: 4,
  },
  'downwind-right': {
    id: 'downwind-right',
    label: 'Downwind right',
    u: -1,
    v: 4,
    distNm: 4,
  },
  'vectors-left': { id: 'vectors-left', label: 'Vectors left', u: -6, v: -2, distNm: 6 },
  'vectors-right': {
    id: 'vectors-right',
    label: 'Vectors right',
    u: -6,
    v: 2,
    distNm: 6,
  },
  'base-left': { id: 'base-left', label: 'Base left', u: -6, v: -4, distNm: 6 },
  'base-right': { id: 'base-right', label: 'Base right', u: -6, v: 4, distNm: 6 },
  'final-3nm': { id: 'final-3nm', label: '3 NM final', u: -3, v: 0, distNm: null },
  'final-8nm': { id: 'final-8nm', label: '8 NM final', u: -8, v: 0, distNm: null },
};

/** True for the two markers the final-distance selector drives. */
export function isFinalMarker(id: MarkerId): boolean {
  return id === 'final-3nm' || id === 'final-8nm';
}

/**
 * How far from the threshold this marker places, in NM.
 *
 * The two final markers answer with the tab's selected final rather than with the dot they
 * draw: the diagram keeps its two illustrative dots, the selector is what places.
 */
export function markerDistanceNm(id: MarkerId, final: FinalPlacementName): number {
  return isFinalMarker(id) ? FINAL_DISTANCE_NM[final] : (CIRCUIT_MARKERS[id].distNm ?? 0);
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
