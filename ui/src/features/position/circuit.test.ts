import { describe, expect, it } from 'vitest';
import { CX, CY, centrelineTicks, place, windArrowRotation } from './circuit';

describe('place', () => {
  it('puts the threshold (u=0, v=0) at the documented centre offset', () => {
    // UMID = -3.2 NM, K = 40 px/NM: the threshold sits 128 px "above" the geometric
    // centre before any rotation (course 0).
    const p = place(0, 0, 0);
    expect(p.x).toBeCloseTo(CX, 6);
    expect(p.y).toBeCloseTo(CY - 128, 6);
  });

  it('places two along-track points exactly 80 px apart, proving the fixed K=40', () => {
    const a = place(-2, 0, 73);
    const b = place(-4, 0, 73);
    const distance = Math.hypot(b.x - a.x, b.y - a.y);
    expect(distance).toBeCloseTo(80, 6);
  });

  it('rotates along-track motion onto the screen x-axis at a 90° course', () => {
    const a = place(-2, 0, 90);
    const b = place(-4, 0, 90);
    expect(a.y).toBeCloseTo(CY, 6);
    expect(b.y).toBeCloseTo(CY, 6);
    expect(a.x).not.toBeCloseTo(b.x, 3);
  });

  it('rotates cross-track motion onto the screen x-axis at a 0° course', () => {
    const a = place(0, -2, 0);
    const b = place(0, 2, 0);
    expect(a.y).toBeCloseTo(b.y, 6);
    expect(a.x).not.toBeCloseTo(b.x, 3);
  });
});

describe('centrelineTicks', () => {
  it('generates every step from the range, inclusive', () => {
    expect(centrelineTicks(-8, 0, 2)).toEqual([-8, -6, -4, -2, 0]);
  });

  it('defaults to a 2 NM step', () => {
    expect(centrelineTicks(0, 4)).toEqual([0, 2, 4]);
  });
});

describe('windArrowRotation', () => {
  it('points downwind — 180° from the wind direction', () => {
    expect(windArrowRotation(240)).toBe(60);
    expect(windArrowRotation(0)).toBe(180);
  });

  it('wraps past 360°', () => {
    expect(windArrowRotation(270)).toBe(90);
  });
});
