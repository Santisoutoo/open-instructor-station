/**
 * The 9 circuit markers drawn on the Approach training tab's diagram, and where their
 * labels sit relative to the dot.
 */

import { place } from './circuit';
import type { MarkerId } from './positionDesignSlice';

export type AltitudeReference = 'MSL' | 'AAL';

export interface CircuitMarker {
  readonly id: MarkerId;
  readonly label: string;
  /** Along-track NM, negative = before the threshold (on approach). */
  readonly u: number;
  /** Cross-track NM, negative = left of centreline. */
  readonly v: number;
  readonly sub: string;
  readonly distNm: number;
  readonly altFt: number;
  readonly altRef: AltitudeReference;
  /** Added to the runway's true course, mod 360, to get this marker's heading. */
  readonly headingOffsetDeg: number;
  readonly note: string;
}

/** `Record<MarkerId, …>` — every id in the closed set is covered, checked at compile time. */
export const CIRCUIT_MARKERS: Record<MarkerId, CircuitMarker> = {
  takeoff: {
    id: 'takeoff',
    label: 'Take off',
    u: 0,
    v: 0,
    sub: 'on threshold · 12 ft',
    distNm: 0,
    altFt: 12,
    altRef: 'MSL',
    headingOffsetDeg: 0,
    note: 'Lined up on the runway, brakes set',
  },
  'downwind-left': {
    id: 'downwind-left',
    label: 'Downwind left',
    u: -1,
    v: -4,
    sub: '4 NM abeam · 1,500 ft',
    distNm: 4,
    altFt: 1500,
    altRef: 'AAL',
    headingOffsetDeg: 180,
    note: 'Left-hand pattern, 1 NM behind the threshold',
  },
  'downwind-right': {
    id: 'downwind-right',
    label: 'Downwind right',
    u: -1,
    v: 4,
    sub: '4 NM abeam · 1,500 ft',
    distNm: 4,
    altFt: 1500,
    altRef: 'AAL',
    headingOffsetDeg: 180,
    note: 'Right-hand pattern, 1 NM behind the threshold',
  },
  'vectors-left': {
    id: 'vectors-left',
    label: 'Vectors left',
    u: -6,
    v: -2,
    sub: '2 NM offset · 1,800 ft',
    distNm: 6,
    altFt: 1800,
    altRef: 'AAL',
    headingOffsetDeg: 90,
    note: '2 NM left of the centerline, intercept heading',
  },
  'vectors-right': {
    id: 'vectors-right',
    label: 'Vectors right',
    u: -6,
    v: 2,
    sub: '2 NM offset · 1,800 ft',
    distNm: 6,
    altFt: 1800,
    altRef: 'AAL',
    headingOffsetDeg: 270,
    note: '2 NM right of the centerline, intercept heading',
  },
  'base-left': {
    id: 'base-left',
    label: 'Base left',
    u: -6,
    v: -4,
    sub: '6 NM final · 1,800 ft',
    distNm: 6,
    altFt: 1800,
    altRef: 'AAL',
    headingOffsetDeg: 90,
    note: 'Turning base from the left',
  },
  'base-right': {
    id: 'base-right',
    label: 'Base right',
    u: -6,
    v: 4,
    sub: '6 NM final · 1,800 ft',
    distNm: 6,
    altFt: 1800,
    altRef: 'AAL',
    headingOffsetDeg: 270,
    note: 'Turning base from the right',
  },
  'final-3nm': {
    id: 'final-3nm',
    label: '3 NM final',
    u: -3,
    v: 0,
    sub: '900 ft · on path',
    distNm: 3,
    altFt: 900,
    altRef: 'AAL',
    headingOffsetDeg: 0,
    note: 'Established on the 3° path',
  },
  'final-8nm': {
    id: 'final-8nm',
    label: '8 NM final',
    u: -8,
    v: 0,
    sub: '2,400 ft · on path',
    distNm: 8,
    altFt: 2400,
    altRef: 'AAL',
    headingOffsetDeg: 0,
    note: 'Established on the 3° path',
  },
};

/** This marker's heading for a runway of true course `courseDeg`. */
export function markerHeading(id: MarkerId, courseDeg: number): number {
  return (courseDeg + CIRCUIT_MARKERS[id].headingOffsetDeg + 360) % 360;
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
