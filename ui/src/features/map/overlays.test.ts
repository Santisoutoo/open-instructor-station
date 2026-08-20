/**
 * The pure geometry builders (instructor-map.md §8.5), against hand-built fixtures
 * matching the generated types — never a copy of real navdata. The ILS feather's
 * bearings are checked with `measure.ts`'s own `initialBearingDeg`, dog-fooding the
 * same module that draws it, exactly as the retired `mock.ts` did informally.
 */

import { describe, expect, it } from 'vitest';
import type {
  GeoPosition,
  Hold,
  Ils,
  Navaid,
  Procedure,
  ProcedureLeg,
  Runway,
  Waypoint,
} from '../../api/models';
import { distanceNm, initialBearingDeg, type LatLon } from './measure';
import {
  ILS_FEATHER_FALLBACK_HALF_ANGLE_DEG,
  ILS_FEATHER_LENGTH_NM,
  fixFeature,
  holdFeature,
  ilsFeature,
  navaidFeature,
  primaryRunwayEnds,
  procedureLineFeature,
  runwayFeature,
} from './overlays';

function geo(lat: number, lon: number, altitudeFt = 0): GeoPosition {
  return { latitude: lat, longitude: lon, altitude_ft: altitudeFt };
}

function toLatLon([lon, lat]: number[]): LatLon {
  return { lat: lat as number, lon: lon as number };
}

function runway(overrides: Partial<Runway> = {}): Runway {
  return {
    airport_icao: 'LEMD',
    ident: '32L',
    threshold: geo(40.46, -3.57),
    true_bearing_deg: 323,
    length_m: 3500,
    elevation_ft: 1998,
    displaced_threshold_m: 0,
    ...overrides,
  };
}

function ils(overrides: Partial<Ils> = {}): Ils {
  return {
    airport_icao: 'LEMD',
    runway_ident: '32L',
    localizer_ident: 'IML',
    frequency_khz: 109_900,
    localizer_position: geo(40.49, -3.6),
    localizer_true_deg: 323,
    localizer_mag_deg: 322,
    has_dme: false,
    ...overrides,
  };
}

describe('runwayFeature', () => {
  it('draws a closed rectangle one pavement length long', () => {
    const feature = runwayFeature(runway());
    const ring = feature.geometry.coordinates[0] as number[][];

    expect(feature.properties.ident).toBe('32L');
    expect(ring).toHaveLength(5);
    expect(ring[0]).toEqual(ring[4]);

    // The midpoint of the far edge sits one length down the bearing.
    const [, , c, d] = ring as [number[], number[], number[], number[]];
    const farMid: LatLon = {
      lat: ((c[1] as number) + (d[1] as number)) / 2,
      lon: ((c[0] as number) + (d[0] as number)) / 2,
    };
    expect(distanceNm({ lat: 40.46, lon: -3.57 }, farMid)).toBeCloseTo(3500 / 1852, 2);
    expect(initialBearingDeg({ lat: 40.46, lon: -3.57 }, farMid)).toBeCloseTo(323, 0);
  });

  it('starts at the pavement end, not the displaced threshold, when published', () => {
    const pavementEnd = geo(40.455, -3.565);
    const feature = runwayFeature(
      runway({ pavement_end: pavementEnd, displaced_threshold_m: 500 }),
    );
    const ring = feature.geometry.coordinates[0] as number[][];
    const nearMid: LatLon = {
      lat: (((ring[0] as number[])[1] as number) + ((ring[1] as number[])[1] as number)) / 2,
      lon: (((ring[0] as number[])[0] as number) + ((ring[1] as number[])[0] as number)) / 2,
    };
    expect(distanceNm({ lat: 40.455, lon: -3.565 }, nearMid)).toBeLessThan(0.05);
  });
});

describe('primaryRunwayEnds', () => {
  it('keeps one rectangle per strip and any lone end', () => {
    const eighteen = runway({ ident: '18L', opposite_ident: '36R' });
    const thirtySix = runway({ ident: '36R', opposite_ident: '18L' });
    const lone = runway({ ident: '07', opposite_ident: '25' }); // 25 not in the list
    const kept = primaryRunwayEnds([thirtySix, eighteen, lone]);
    expect(kept.map((end) => end.ident).sort()).toEqual(['07', '18L']);
  });
});

describe('ilsFeature', () => {
  it('is null for a runway end without an ILS', () => {
    expect(ilsFeature(runway())).toBeNull();
  });

  it('opens the feather down the reciprocal of the front course, half the published width each side', () => {
    const feature = ilsFeature(runway({ ils: ils({ localizer_width_deg: 4 }) }));
    expect(feature).not.toBeNull();
    const coords = feature!.geometry.coordinates as number[][];

    // Closed triangle: apex, left, right, apex.
    expect(coords).toHaveLength(4);
    expect(coords[0]).toEqual(coords[3]);

    const apex = toLatLon(coords[0] as number[]);
    const left = toLatLon(coords[1] as number[]);
    const right = toLatLon(coords[2] as number[]);
    const approach = (323 + 180) % 360; // 143

    expect(initialBearingDeg(apex, left)).toBeCloseTo(approach - 2, 1);
    expect(initialBearingDeg(apex, right)).toBeCloseTo(approach + 2, 1);
    expect(distanceNm(apex, left)).toBeCloseTo(ILS_FEATHER_LENGTH_NM, 3);
  });

  it('falls back to the nominal half-angle when no width is published', () => {
    const feature = ilsFeature(runway({ ils: ils() }));
    const coords = feature!.geometry.coordinates as number[][];
    const apex = toLatLon(coords[0] as number[]);
    const left = toLatLon(coords[1] as number[]);
    expect(initialBearingDeg(apex, left)).toBeCloseTo(
      143 - ILS_FEATHER_FALLBACK_HALF_ANGLE_DEG,
      1,
    );
  });
});

describe('navaidFeature and fixFeature', () => {
  it('emit lon-lat points carrying ident (and kind for navaids)', () => {
    const navaid: Navaid = {
      ident: 'SSY',
      kind: 'vor',
      position: geo(40.5, -3.6),
      tunable_radio: 'nav',
    };
    const point = navaidFeature(navaid);
    expect(point.geometry.coordinates).toEqual([-3.6, 40.5]);
    expect(point.properties).toEqual({ ident: 'SSY', kind: 'vor' });

    const fix = fixFeature({ ident: 'GOXOL', position: geo(40.2, -3.1) });
    expect(fix.geometry.coordinates).toEqual([-3.1, 40.2]);
    expect(fix.properties).toEqual({ ident: 'GOXOL' });
  });
});

function waypoint(ident: string, lat: number, lon: number): Waypoint {
  return { ident, kind: 'fix', position: geo(lat, lon) };
}

function leg(
  sequence: number,
  pathTerminator: ProcedureLeg['path_terminator'],
  fix: Waypoint | null,
): ProcedureLeg {
  return {
    sequence,
    path_terminator: pathTerminator,
    is_positionable: fix !== null,
    fix,
    is_flyover: false,
    is_initial_approach_fix: false,
    is_final_approach_fix: false,
    is_missed_approach_point: false,
    is_missed_approach_leg: false,
    is_end_of_procedure: false,
  };
}

describe('procedureLineFeature', () => {
  it('breaks the line at a trajectory-only leg instead of inventing a point', () => {
    const procedure: Procedure = {
      airport_icao: 'LEMD',
      kind: 'sid',
      ident: 'BARD3B',
      runway_idents: ['32L'],
      legs: [
        leg(10, 'IF', waypoint('AAAAA', 40.5, -3.5)),
        leg(20, 'TF', waypoint('BBBBB', 40.6, -3.4)),
        leg(30, 'CA', null), // the climbing turn: no fix, no defensible coordinate
        leg(40, 'TF', waypoint('CCCCC', 40.8, -3.2)),
        leg(50, 'TF', waypoint('DDDDD', 40.9, -3.1)),
      ],
    };
    const feature = procedureLineFeature(procedure);

    // Two runs either side of the break; total coordinates equal the
    // fix-carrying leg count, never the total leg count.
    expect(feature.geometry.coordinates).toHaveLength(2);
    const total = feature.geometry.coordinates.reduce(
      (count, segment) => count + segment.length,
      0,
    );
    expect(total).toBe(4);
    expect(feature.geometry.coordinates[0]).toEqual([
      [-3.5, 40.5],
      [-3.4, 40.6],
    ]);
    expect(feature.properties).toEqual({
      ident: 'BARD3B',
      kind: 'sid',
      transition: null,
    });
  });

  it('connects legs in sequence order regardless of array order', () => {
    const procedure: Procedure = {
      airport_icao: 'LEMD',
      kind: 'star',
      ident: 'TERSA1',
      runway_idents: [],
      legs: [
        leg(20, 'TF', waypoint('BBBBB', 40.6, -3.4)),
        leg(10, 'IF', waypoint('AAAAA', 40.5, -3.5)),
      ],
    };
    expect(procedureLineFeature(procedure).geometry.coordinates[0]).toEqual([
      [-3.5, 40.5],
      [-3.4, 40.6],
    ]);
  });
});

describe('holdFeature', () => {
  it('draws a closed racetrack whose inbound leg arrives at the fix on the published course', () => {
    const hold: Hold = {
      fix: waypoint('GOXOL', 40.2, -3.1),
      inbound_course_mag_deg: 90,
      turn_direction: 'R',
      leg_length_nm: 5,
    };
    const feature = holdFeature(hold);
    const coords = feature.geometry.coordinates as number[][];

    const inboundStart = toLatLon(coords[0] as number[]);
    const fix = toLatLon(coords[1] as number[]);
    expect(fix.lat).toBeCloseTo(40.2, 6);
    expect(fix.lon).toBeCloseTo(-3.1, 6);
    // ±0.5°: the *initial* bearing of a 5 NM great circle at 40°N differs from the
    // course flown at the fix by meridian convergence (~0.07°) — real, not a bug.
    expect(initialBearingDeg(inboundStart, fix)).toBeCloseTo(90, 0);
    expect(distanceNm(inboundStart, fix)).toBeCloseTo(5, 3);

    // Closed: the final half-turn ends back at the inbound leg's start.
    const last = toLatLon(coords[coords.length - 1] as number[]);
    expect(last.lat).toBeCloseTo(inboundStart.lat, 6);
    expect(last.lon).toBeCloseTo(inboundStart.lon, 6);

    expect(feature.properties).toEqual({ fix_ident: 'GOXOL', turn_direction: 'R' });
  });

  it('derives a leg length from the published time when no distance is stated', () => {
    const timed: Hold = {
      fix: waypoint('GOXOL', 40.2, -3.1),
      inbound_course_mag_deg: 270,
      turn_direction: 'L',
      leg_time_min: 1,
    };
    const coords = holdFeature(timed).geometry.coordinates as number[][];
    const inboundStart = toLatLon(coords[0] as number[]);
    const fix = toLatLon(coords[1] as number[]);
    expect(distanceNm(inboundStart, fix)).toBeCloseTo(3, 2);
  });
});
