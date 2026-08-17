/**
 * The grading thresholds at their edges: on the boundary is still the milder
 * grade, one past it is the harsher one, and magnitudes judge both signs alike.
 */

import { describe, expect, it } from 'vitest';
import { gradeMetric, gradeReport } from './grade';
import { MOCK_LANDINGS } from './mock';

describe('gradeMetric', () => {
  it('touchdown rate: boundary-inclusive ok, then warn, then danger, sign-blind', () => {
    expect(gradeMetric('touchdown_vs_fpm', -250)).toBe('ok');
    expect(gradeMetric('touchdown_vs_fpm', -251)).toBe('warn');
    expect(gradeMetric('touchdown_vs_fpm', -600)).toBe('warn');
    expect(gradeMetric('touchdown_vs_fpm', -601)).toBe('danger');
  });

  it('peak G judges the excess over level flight', () => {
    expect(gradeMetric('peak_g', 1.0)).toBe('ok');
    expect(gradeMetric('peak_g', 1.4)).toBe('ok');
    expect(gradeMetric('peak_g', 1.5)).toBe('warn');
    expect(gradeMetric('peak_g', 1.9)).toBe('danger');
  });

  it('pitch judges the distance from the target attitude, both directions', () => {
    expect(gradeMetric('pitch_at_touchdown_deg', 4)).toBe('ok');
    expect(gradeMetric('pitch_at_touchdown_deg', 7)).toBe('ok');
    expect(gradeMetric('pitch_at_touchdown_deg', 8)).toBe('warn');
    expect(gradeMetric('pitch_at_touchdown_deg', 0)).toBe('warn');
    expect(gradeMetric('pitch_at_touchdown_deg', -1.5)).toBe('danger');
    expect(gradeMetric('pitch_at_touchdown_deg', 9.5)).toBe('danger');
  });

  it('centreline offset grades by magnitude on either side', () => {
    expect(gradeMetric('centreline_offset_m', -3)).toBe('ok');
    expect(gradeMetric('centreline_offset_m', 5)).toBe('warn');
    expect(gradeMetric('centreline_offset_m', -9)).toBe('danger');
  });

  it('threshold speed judges against Vref both fast and slow', () => {
    expect(gradeMetric('ias_at_threshold_kt', 92)).toBe('ok');
    expect(gradeMetric('ias_at_threshold_kt', 97)).toBe('ok');
    expect(gradeMetric('ias_at_threshold_kt', 100)).toBe('warn');
    expect(gradeMetric('ias_at_threshold_kt', 84)).toBe('warn');
    expect(gradeMetric('ias_at_threshold_kt', 110)).toBe('danger');
  });
});

describe('gradeReport', () => {
  it('grades every metric of a report', () => {
    const report = MOCK_LANDINGS[0]!.report;
    const grades = gradeReport(report);
    expect(Object.keys(grades).sort()).toEqual(Object.keys(report).sort());
  });

  it('the good landing grades ok across the board', () => {
    const good = MOCK_LANDINGS.find(({ id }) => id === 'good')!;
    expect(Object.values(gradeReport(good.report)).every((g) => g === 'ok')).toBe(true);
  });

  it('the firm landing flags its sink rate and G', () => {
    const firm = MOCK_LANDINGS.find(({ id }) => id === 'firm')!;
    const grades = gradeReport(firm.report);
    expect(grades.touchdown_vs_fpm).not.toBe('ok');
    expect(grades.peak_g).not.toBe('ok');
  });

  it('the off-centre landing flags the centreline and heading', () => {
    const offCentre = MOCK_LANDINGS.find(({ id }) => id === 'off-centre')!;
    const grades = gradeReport(offCentre.report);
    expect(grades.centreline_offset_m).not.toBe('ok');
    expect(grades.heading_vs_runway_deg).not.toBe('ok');
  });
});
