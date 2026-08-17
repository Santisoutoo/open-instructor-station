/**
 * Invariants of the generated demo landings: the trace is physically coherent, the
 * report matches its own trace, and the four profiles differ in the ways their
 * names promise.
 */

import { describe, expect, it } from 'vitest';
import { MOCK_LANDINGS } from './mock';

function byId(id: string) {
  const landing = MOCK_LANDINGS.find((candidate) => candidate.id === id);
  if (landing === undefined) {
    throw new Error(`no mock landing '${id}'`);
  }
  return landing;
}

describe('MOCK_LANDINGS', () => {
  it('serves the four demo landings', () => {
    expect(MOCK_LANDINGS.map(({ id }) => id)).toEqual([
      'good',
      'firm',
      'floated',
      'off-centre',
    ]);
  });

  it.each(MOCK_LANDINGS.map((landing) => [landing.id, landing] as const))(
    '%s: airborne before the touchdown index, on the ground from it on',
    (_id, landing) => {
      const before = landing.samples.slice(0, landing.touchdownIndex);
      const after = landing.samples.slice(landing.touchdownIndex);
      expect(before.length).toBeGreaterThan(0);
      expect(after.length).toBeGreaterThan(0);
      expect(before.every((sample) => sample.altitude_agl_ft > 0)).toBe(true);
      expect(after.every((sample) => sample.altitude_agl_ft === 0)).toBe(true);
      expect(after.every((sample) => sample.vs_fpm === 0)).toBe(true);
    },
  );

  it.each(MOCK_LANDINGS.map((landing) => [landing.id, landing] as const))(
    '%s: time is strictly increasing and the aircraft always moves forward',
    (_id, landing) => {
      for (let i = 1; i < landing.samples.length; i += 1) {
        const previous = landing.samples[i - 1];
        const current = landing.samples[i];
        expect(current!.t_s).toBeGreaterThan(previous!.t_s);
        expect(current!.distance_from_threshold_m).toBeGreaterThan(
          previous!.distance_from_threshold_m,
        );
      }
    },
  );

  it.each(MOCK_LANDINGS.map((landing) => [landing.id, landing] as const))(
    '%s: the report is derived from its own trace',
    (_id, landing) => {
      const lastAirborne = landing.samples[landing.touchdownIndex - 1]!;
      const touchdown = landing.samples[landing.touchdownIndex]!;
      expect(landing.report.touchdown_vs_fpm).toBe(lastAirborne.vs_fpm);
      expect(landing.report.pitch_at_touchdown_deg).toBe(touchdown.pitch_deg);
      expect(landing.report.touchdown_distance_m).toBeCloseTo(
        touchdown.distance_from_threshold_m,
        -1,
      );
      // Touchdown past the threshold, within the first kilometre and a half.
      expect(landing.report.touchdown_distance_m).toBeGreaterThan(0);
      expect(landing.report.touchdown_distance_m).toBeLessThan(1500);
    },
  );

  it('is deterministic: two imports of the module see identical fixtures', () => {
    // Same-module identity is trivial; what matters is no clock and no randomness,
    // which the generation encodes — spot-check a value that would drift otherwise.
    expect(byId('good').samples[0]!.t_s).toBe(0.25);
    expect(byId('good').recorded_at).toBe('2026-08-14T16:20:00Z');
  });

  it('the firm landing hits harder than the good one', () => {
    expect(Math.abs(byId('firm').report.touchdown_vs_fpm)).toBeGreaterThan(
      Math.abs(byId('good').report.touchdown_vs_fpm) + 100,
    );
    expect(byId('firm').report.peak_g).toBeGreaterThan(byId('good').report.peak_g);
  });

  it('the floated landing floats furthest and lands deepest', () => {
    const floated = byId('floated');
    for (const other of MOCK_LANDINGS.filter(({ id }) => id !== 'floated')) {
      expect(floated.report.float_distance_m).toBeGreaterThan(
        other.report.float_distance_m,
      );
      expect(floated.report.touchdown_distance_m).toBeGreaterThan(
        other.report.touchdown_distance_m,
      );
    }
    expect(floated.report.ias_at_threshold_kt).toBeGreaterThan(
      byId('good').report.ias_at_threshold_kt,
    );
  });

  it('the off-centre landing is the one away from the centreline', () => {
    const offCentre = byId('off-centre');
    for (const other of MOCK_LANDINGS.filter(({ id }) => id !== 'off-centre')) {
      expect(Math.abs(offCentre.report.centreline_offset_m)).toBeGreaterThan(
        Math.abs(other.report.centreline_offset_m),
      );
    }
  });
});
