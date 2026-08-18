/**
 * The client-side arc against the design's hand-checkable numbers (§3, §8.1), and —
 * above all — D5 pinned: `direction` is where the NOSE ends up, so 'right' rotates
 * the final heading CLOCKWISE. The opposite tail-swing convention is equally
 * defensible, which is exactly why this suite nails the chosen one down.
 */

import { describe, expect, it } from 'vitest';
import { finalHeadingDeg, pushbackPathLocal, signedAngleDeg } from './arc';
import { PUSHBACK_PATH_PREVIEW_POINTS } from './types.mock';

/** The §3 worked example: distance 30 m, angle 90° → radius 60/π, chord ≈ 27.0095 m. */
const RADIUS_M = 30 / (Math.PI / 2);
const CHORD_M = 2 * RADIUS_M * Math.sin(Math.PI / 4);

describe('signedAngleDeg (D5)', () => {
  it('is positive — clockwise — for right, negative for left, zero for straight', () => {
    expect(signedAngleDeg('right', 45)).toBe(45);
    expect(signedAngleDeg('left', 45)).toBe(-45);
    expect(signedAngleDeg('straight', 0)).toBe(0);
  });
});

describe('finalHeadingDeg (D5)', () => {
  it('rotates the nose clockwise on a right push: 090 + 90 = 180 exactly', () => {
    expect(finalHeadingDeg(90, 'right', 90)).toBe(180);
  });

  it('rotates the nose counter-clockwise on a left push: 090 − 90 = 000', () => {
    expect(finalHeadingDeg(90, 'left', 90)).toBe(0);
  });

  it('leaves the heading alone on a straight push', () => {
    expect(finalHeadingDeg(123, 'straight', 0)).toBe(123);
  });

  it('wraps through north in both directions', () => {
    expect(finalHeadingDeg(350, 'right', 20)).toBe(10);
    expect(finalHeadingDeg(10, 'left', 20)).toBe(350);
  });
});

describe('pushbackPathLocal', () => {
  it('returns PUSHBACK_PATH_PREVIEW_POINTS + 1 points, origin first', () => {
    const path = pushbackPathLocal('right', 30, 90);

    expect(path).toHaveLength(PUSHBACK_PATH_PREVIEW_POINTS + 1);
    expect(path[0]).toEqual({ x: 0, y: 0 });
  });

  it('pushes straight back along the tail: collinear, ending 20 m behind', () => {
    const path = pushbackPathLocal('straight', 20, 0);

    for (const point of path) {
      expect(point.x).toBeCloseTo(0, 9);
    }
    expect(path.at(-1)?.y).toBeCloseTo(-20, 9);
  });

  it('lands the §3 worked example: right 30 m / 90° ends behind-LEFT of the start', () => {
    const end = pushbackPathLocal('right', 30, 90).at(-1);

    // Chord ≈ 27.0095 m at a local bearing of 180 + 90/2 = 225°: the nose swings
    // right, the tail swings left, the aircraft ends behind and to the left.
    expect(Math.hypot(end?.x ?? 0, end?.y ?? 0)).toBeCloseTo(CHORD_M, 4);
    expect(end?.x).toBeCloseTo(CHORD_M * Math.sin((225 * Math.PI) / 180), 4);
    expect(end?.y).toBeCloseTo(CHORD_M * Math.cos((225 * Math.PI) / 180), 4);
  });

  it('mirrors the same arc for a left push: behind-RIGHT of the start', () => {
    const end = pushbackPathLocal('left', 30, 90).at(-1);

    expect(end?.x).toBeCloseTo(CHORD_M * Math.sin((135 * Math.PI) / 180), 4);
    expect(end?.y).toBeCloseTo(CHORD_M * Math.cos((135 * Math.PI) / 180), 4);
  });

  it('keeps every intermediate point on the same circle (§6, no integration drift)', () => {
    // For a right push the arc's centre sits abeam the start, one radius to the
    // LEFT of the nose: (−r, 0). Every point must stay a radius away from it.
    const path = pushbackPathLocal('right', 30, 90);

    for (const point of path) {
      expect(Math.hypot(point.x + RADIUS_M, point.y)).toBeCloseTo(RADIUS_M, 6);
    }
  });

  it('handles the 180° U-turn: the end sits exactly one diameter abeam the start', () => {
    const end = pushbackPathLocal('right', 30, 180).at(-1);
    const radiusM = 30 / Math.PI;

    // Full chord at 180° is the diameter, at a local bearing of 180 + 90 = 270°.
    expect(end?.x).toBeCloseTo(-2 * radiusM, 6);
    expect(end?.y).toBeCloseTo(0, 6);
  });
});
