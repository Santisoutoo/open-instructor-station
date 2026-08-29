/**
 * The measure tool's geodesy against known answers: a degree of latitude is 60 NM,
 * cardinal bearings come out cardinal, and destination/distance round-trip.
 */

import { describe, expect, it } from 'vitest';
import {
  destinationPoint,
  distanceNm,
  formatMeasure,
  initialBearingDeg,
} from './measure';

const LEMD = { lat: 40.47, lon: -3.56 };

describe('distanceNm', () => {
  it('measures one degree of latitude as sixty nautical miles', () => {
    const a = { lat: 40, lon: -3.56 };
    const b = { lat: 41, lon: -3.56 };
    expect(distanceNm(a, b)).toBeCloseTo(60.04, 1);
  });

  it('is zero from a point to itself', () => {
    expect(distanceNm(LEMD, LEMD)).toBe(0);
  });

  it('is symmetric', () => {
    const b = { lat: 41.3, lon: 2.08 };
    expect(distanceNm(LEMD, b)).toBeCloseTo(distanceNm(b, LEMD), 10);
  });
});

describe('initialBearingDeg', () => {
  it('points north along a meridian', () => {
    expect(initialBearingDeg({ lat: 40, lon: -3 }, { lat: 41, lon: -3 })).toBeCloseTo(
      0,
      6,
    );
  });

  it('points east along the equator', () => {
    expect(initialBearingDeg({ lat: 0, lon: 0 }, { lat: 0, lon: 1 })).toBeCloseTo(90, 6);
  });

  it('normalises westbound bearings into [0, 360)', () => {
    const bearing = initialBearingDeg({ lat: 40, lon: -3 }, { lat: 40, lon: -4 });
    expect(bearing).toBeGreaterThan(180);
    expect(bearing).toBeLessThan(360);
  });
});

describe('destinationPoint', () => {
  it('round-trips with distance and bearing', () => {
    const there = destinationPoint(LEMD, 143, 10);
    expect(distanceNm(LEMD, there)).toBeCloseTo(10, 6);
    expect(initialBearingDeg(LEMD, there)).toBeCloseTo(143, 2);
  });

  it('going north raises only the latitude', () => {
    const there = destinationPoint(LEMD, 0, 60);
    expect(there.lon).toBeCloseTo(LEMD.lon, 6);
    expect(there.lat).toBeGreaterThan(LEMD.lat);
  });
});

describe('formatMeasure', () => {
  it('renders a padded aviation bearing and one-decimal distance', () => {
    expect(formatMeasure(12.42, 7)).toBe('12.4 NM · 007°');
  });

  it('normalises the bearing before padding', () => {
    expect(formatMeasure(1, 360)).toBe('1.0 NM · 000°');
    expect(formatMeasure(1, -17)).toBe('1.0 NM · 343°');
  });
});
