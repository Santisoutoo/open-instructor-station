/**
 * The chart plumbing against known answers: scales map endpoints exactly, ticks
 * come out round and inside the domain, and the polyline string is SVG-shaped.
 */

import { describe, expect, it } from 'vitest';
import { linearScale, paddedExtent, polylinePoints, ticks } from './scale';

describe('linearScale', () => {
  it('maps the domain endpoints onto the range endpoints', () => {
    const scale = linearScale([0, 10], [100, 0]);
    expect(scale(0)).toBe(100);
    expect(scale(10)).toBe(0);
    expect(scale(5)).toBe(50);
  });

  it('pins a degenerate domain to the middle of the range', () => {
    const scale = linearScale([7, 7], [0, 100]);
    expect(scale(7)).toBe(50);
  });
});

describe('paddedExtent', () => {
  it('pads the raw extent on both sides', () => {
    const [min, max] = paddedExtent([10, 20]);
    expect(min).toBeLessThan(10);
    expect(max).toBeGreaterThan(20);
  });

  it('still produces a usable span for constant data', () => {
    const [min, max] = paddedExtent([5, 5, 5]);
    expect(max).toBeGreaterThan(min);
  });

  it('falls back to [0, 1] on empty input', () => {
    expect(paddedExtent([])).toEqual([0, 1]);
  });
});

describe('ticks', () => {
  it('picks round steps inside the domain', () => {
    const result = ticks(0, 100, 4);
    expect(result).toEqual([0, 25, 50, 75, 100]);
  });

  it('never emits a tick outside the domain', () => {
    for (const tick of ticks(-3.7, 12.2, 4)) {
      expect(tick).toBeGreaterThanOrEqual(-3.7);
      expect(tick).toBeLessThanOrEqual(12.2);
    }
  });

  it('handles a zero-span domain with a single tick', () => {
    expect(ticks(4, 4)).toEqual([4]);
  });
});

describe('polylinePoints', () => {
  it('renders x,y pairs separated by spaces', () => {
    const x = linearScale([0, 1], [0, 100]);
    const y = linearScale([0, 1], [100, 0]);
    const points = polylinePoints(
      [
        { t: 0, v: 0 },
        { t: 1, v: 1 },
      ],
      (s) => s.t,
      (s) => s.v,
      x,
      y,
    );
    expect(points).toBe('0.0,100.0 100.0,0.0');
  });
});
