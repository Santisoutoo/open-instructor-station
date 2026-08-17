/**
 * The flat-earth geometry under the mock feed. The invariant that matters is the
 * round trip: a point placed `offset(origin, bearing, distance)` away must measure
 * back that same bearing and distance — the relative-position line in the list is
 * only honest if these three functions agree with each other.
 */

import { describe, expect, it } from 'vitest';
import { advanceEntity, bearingDeg, distanceNm, normalizeDeg, offset } from './geo';
import type { LatLon, TrafficEntity } from './types.mock';

const MADRID: LatLon = { lat: 40.46, lon: -3.57 };

function entity(overrides: Partial<TrafficEntity> = {}): TrafficEntity {
  return {
    id: 'TFC-001',
    callsign: 'IBE1000',
    kind: 'aircraft',
    position: MADRID,
    altitude_ft: 5000,
    heading_deg: 90,
    speed_kt: 360,
    track: [],
    ...overrides,
  };
}

/** Smallest angular difference between two bearings, in degrees. */
function angularDiff(a: number, b: number): number {
  const raw = Math.abs(normalizeDeg(a) - normalizeDeg(b));
  return Math.min(raw, 360 - raw);
}

describe('normalizeDeg', () => {
  it('maps any angle into [0, 360)', () => {
    expect(normalizeDeg(0)).toBe(0);
    expect(normalizeDeg(360)).toBe(0);
    expect(normalizeDeg(-90)).toBe(270);
    expect(normalizeDeg(725)).toBe(5);
  });
});

describe('offset', () => {
  it('moves due north along the meridian: 60 NM is one degree of latitude', () => {
    const north = offset(MADRID, 0, 60);
    expect(north.lat).toBeCloseTo(MADRID.lat + 1, 6);
    expect(north.lon).toBeCloseTo(MADRID.lon, 6);
  });

  it('moves due east without changing latitude', () => {
    const east = offset(MADRID, 90, 10);
    expect(east.lat).toBeCloseTo(MADRID.lat, 6);
    expect(east.lon).toBeGreaterThan(MADRID.lon);
  });
});

describe('offset / distanceNm / bearingDeg round trip', () => {
  it.each([0, 45, 90, 135, 180, 225, 270, 315])(
    'a point placed 10 NM out on bearing %d measures back the same',
    (bearing) => {
      const point = offset(MADRID, bearing, 10);
      expect(distanceNm(MADRID, point)).toBeCloseTo(10, 2);
      expect(angularDiff(bearingDeg(MADRID, point), bearing)).toBeLessThan(0.5);
    },
  );

  it('is symmetric in distance', () => {
    const point = offset(MADRID, 47, 8);
    expect(distanceNm(MADRID, point)).toBeCloseTo(distanceNm(point, MADRID), 6);
  });

  it('reports the reciprocal bearing from the far end', () => {
    const point = offset(MADRID, 90, 10);
    expect(angularDiff(bearingDeg(point, MADRID), 270)).toBeLessThan(0.5);
  });
});

describe('advanceEntity', () => {
  it('flies straight on its heading when the track is empty', () => {
    // 360 kt for 10 s is exactly 1 NM.
    const before = entity({ heading_deg: 90, speed_kt: 360, track: [] });
    const after = advanceEntity(before, 10);

    expect(distanceNm(before.position, after.position)).toBeCloseTo(1, 3);
    expect(angularDiff(bearingDeg(before.position, after.position), 90)).toBeLessThan(
      0.5,
    );
    expect(after.heading_deg).toBe(90);
  });

  it('turns the corner: leftover distance carries onto the next leg', () => {
    // Waypoint 1 NM north, then the route bends east. One tick covers 1.5 NM, so the
    // entity must end up 0.5 NM east of the corner — not 0.5 NM past it heading north.
    const corner = offset(MADRID, 0, 1);
    const exit = offset(corner, 90, 2);
    const before = entity({
      heading_deg: 0,
      speed_kt: 5400, // 1.5 NM per second, keeps the numbers exact
      track: [corner, exit],
    });

    const after = advanceEntity(before, 1);

    const expected = offset(corner, 90, 0.5);
    expect(distanceNm(after.position, expected)).toBeLessThan(0.01);
    expect(angularDiff(after.heading_deg, 90)).toBeLessThan(0.5);
    expect(after.track).toEqual([exit]);
  });

  it('continues straight once the track is exhausted mid-tick', () => {
    const waypoint = offset(MADRID, 90, 1);
    const before = entity({ heading_deg: 90, speed_kt: 7200, track: [waypoint] });

    // 2 NM in one second: 1 NM to the waypoint, 1 NM straight past it.
    const after = advanceEntity(before, 1);

    expect(after.track).toEqual([]);
    expect(distanceNm(MADRID, after.position)).toBeCloseTo(2, 2);
    expect(angularDiff(bearingDeg(MADRID, after.position), 90)).toBeLessThan(0.5);
  });

  it('is a no-op for a zero or negative time step', () => {
    const before = entity();
    expect(advanceEntity(before, 0)).toBe(before);
    expect(advanceEntity(before, -5)).toBe(before);
  });

  it('never mutates the input entity', () => {
    const before = entity({ track: [offset(MADRID, 0, 1)] });
    const trackBefore = [...before.track];
    const positionBefore = { ...before.position };

    advanceEntity(before, 30);

    expect(before.track).toEqual(trackBefore);
    expect(before.position).toEqual(positionBefore);
  });
});
