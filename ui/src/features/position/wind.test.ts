/**
 * `windComponents` / `runwayWind` — ported verbatim from the design doc's formula.
 *
 * The design doc's own test-plan prose gives an illustrative example ("7 kt head" on
 * 04R/04L for the 240°/12 kt sample wind) that does not match applying its own formula to
 * its own sample data (course 40°/220°): the exact formula gives an **11 kt tailwind** on
 * the 040-courses and an **11 kt headwind** on the 220-courses for that wind. The formula
 * section is the authoritative, testable spec; this suite asserts what it actually computes
 * — see the implementation report for the full discrepancy note.
 */

import { describe, expect, it } from 'vitest';
import { approachWindText, runwayWind, windComponents } from './wind';

describe('windComponents', () => {
  it('is a pure headwind on the nose', () => {
    const { head, cross, tail } = windComponents(360, 20, 360);
    expect(head).toBe(20);
    expect(cross).toBe(0);
    expect(tail).toBe(0);
  });

  it('is zero cross and zero head/tail when the wind is exactly abeam', () => {
    const { head, cross, tail } = windComponents(90, 20, 0);
    expect(head).toBe(0);
    expect(cross).toBe(20);
    expect(tail).toBe(0);
  });

  it('is a pure tailwind 180° off the nose', () => {
    const { head, cross, tail } = windComponents(180, 20, 0);
    expect(head).toBe(-20);
    expect(cross).toBe(0);
    expect(tail).toBe(20);
  });

  it('wraps cleanly across the 360°/0° boundary', () => {
    const at350 = windComponents(350, 20, 10);
    const at010 = windComponents(10, 20, 350);
    // Both are 20° off the nose, one on each side — same headwind magnitude.
    expect(at350.head).toBe(at010.head);
    expect(at350.head).toBeGreaterThan(0);
  });

  it('head and tail are mutually exclusive — tail is only ever the unsigned tailwind', () => {
    for (const windDeg of [0, 45, 90, 135, 180, 225, 270, 315]) {
      const { head, tail } = windComponents(windDeg, 15, 40);
      // Never both a reported headwind and a reported tailwind at once.
      expect(head > 0 && tail > 0).toBe(false);
      expect(tail).toBe(head < 0 ? -head : 0);
    }
  });
});

describe('runwayWind against the sample 240°/12 kt wind', () => {
  it('produces the tab strings for the 5-runway table', () => {
    // Courses 40°/40° (04R/04L) are 160° off the wind — an 11 kt tailwind. Courses
    // 220°/220° (22L/22R) are 20° off — an 11 kt headwind.
    expect(runwayWind(240, 12, 40)).toEqual({ text: '11 kt tail', caution: true });
    expect(runwayWind(240, 12, 220)).toEqual({ text: '11 kt head', caution: false });
  });
});

describe('approachWindText', () => {
  it('combines the longitudinal and cross components with a middle dot', () => {
    expect(approachWindText(240, 12, 40)).toBe('11 kt tail · 4 kt cross');
    expect(approachWindText(240, 12, 220)).toBe('11 kt head · 4 kt cross');
  });
});
