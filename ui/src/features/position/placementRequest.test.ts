/**
 * The marker → placement mapping, asserted as the whole request the server would receive.
 *
 * These are the exact bodies `POST /api/position/preview` and `/apply` are sent, so the
 * table in the module docstring is not documentation that can drift: it is this suite.
 */

import { describe, expect, it } from 'vitest';
import { FINAL_DISTANCE_NM, FINAL_LABELS, FINAL_ORDER } from './finals';
import { buildPlacementRequest, type PlacementInputs } from './placementRequest';
import { MARKER_IDS } from './positionDesignSlice';

function inputs(overrides: Partial<PlacementInputs> = {}): PlacementInputs {
  return {
    icao: 'LFMN',
    runwayIdent: '04R',
    standName: null,
    activeTab: 'approach',
    marker: 'final-3nm',
    finalPlacement: 'final_3nm',
    procedure: null,
    airwork: {
      position: { latitude: 43.6584, longitude: 7.2159, altitude_ft: 10000 },
      headingDeg: 40,
    },
    custom: {
      position: { latitude: 43.5, longitude: 7.1, altitude_ft: 3000 },
      headingDeg: 90,
    },
    ...overrides,
  };
}

describe('no airport, no placement', () => {
  it('answers null rather than a half-built request', () => {
    expect(buildPlacementRequest(inputs({ icao: '' }))).toBeNull();
  });

  it('answers null on the Approach tab with no runway end selected', () => {
    expect(buildPlacementRequest(inputs({ runwayIdent: null }))).toBeNull();
  });
});

describe('the Approach tab markers', () => {
  it('places the takeoff marker on the runway threshold', () => {
    expect(buildPlacementRequest(inputs({ marker: 'takeoff' }))).toEqual({
      type: 'runway_threshold',
      airport_icao: 'LFMN',
      runway_ident: '04R',
    });
  });

  it('places both final markers on the tab’s selected final, not on the dot they draw', () => {
    for (const marker of ['final-3nm', 'final-8nm'] as const) {
      expect(
        buildPlacementRequest(inputs({ marker, finalPlacement: 'final_10nm' })),
      ).toEqual({
        type: 'runway',
        airport_icao: 'LFMN',
        runway_ident: '04R',
        placement: 'final_10nm',
      });
    }
  });

  it('places downwind 4 NM abeam, with no leg distance', () => {
    expect(buildPlacementRequest(inputs({ marker: 'downwind-left' }))).toEqual({
      type: 'runway',
      airport_icao: 'LFMN',
      runway_ident: '04R',
      placement: 'left_downwind',
      pattern_width_nm: 4,
    });
    expect(buildPlacementRequest(inputs({ marker: 'downwind-right' }))).toMatchObject({
      placement: 'right_downwind',
      pattern_width_nm: 4,
    });
  });

  it('places base 4 NM out on a 6 NM leg', () => {
    expect(buildPlacementRequest(inputs({ marker: 'base-left' }))).toEqual({
      type: 'runway',
      airport_icao: 'LFMN',
      runway_ident: '04R',
      placement: 'left_base',
      pattern_width_nm: 4,
      leg_distance_nm: 6,
    });
    expect(buildPlacementRequest(inputs({ marker: 'base-right' }))).toMatchObject({
      placement: 'right_base',
      pattern_width_nm: 4,
      leg_distance_nm: 6,
    });
  });

  it('places vectors as a 2 NM-wide base leg — 6 NM out, 2 NM offset, intercept heading', () => {
    // Not an approximation: core.geodesy.traffic_pattern_point puts a base leg at
    // along = -leg_distance_nm, across = side × pattern_width_nm. Do not "fix" this.
    expect(buildPlacementRequest(inputs({ marker: 'vectors-left' }))).toEqual({
      type: 'runway',
      airport_icao: 'LFMN',
      runway_ident: '04R',
      placement: 'left_base',
      pattern_width_nm: 2,
      leg_distance_nm: 6,
    });
    expect(buildPlacementRequest(inputs({ marker: 'vectors-right' }))).toMatchObject({
      placement: 'right_base',
      pattern_width_nm: 2,
      leg_distance_nm: 6,
    });
  });

  it('produces a request for every marker in the closed set', () => {
    for (const marker of MARKER_IDS) {
      expect(buildPlacementRequest(inputs({ marker }))).not.toBeNull();
    }
  });
});

describe('a selected stand wins over everything', () => {
  it('sends the stand name whichever tab is open', () => {
    for (const tab of ['approach', 'sidstar', 'airwork', 'custom'] as const) {
      expect(buildPlacementRequest(inputs({ standName: 'A3', activeTab: tab }))).toEqual({
        type: 'parking',
        airport_icao: 'LFMN',
        stand_name: 'A3',
      });
    }
  });
});

describe('the SID & STAR tab', () => {
  it('needs a leg before it means anything', () => {
    expect(
      buildPlacementRequest(
        inputs({
          activeTab: 'sidstar',
          procedure: { kind: 'sid', ident: 'BADO8A', transition: null, sequence: null },
        }),
      ),
    ).toBeNull();
  });

  it('sends the leg’s own sequence number', () => {
    expect(
      buildPlacementRequest(
        inputs({
          activeTab: 'sidstar',
          procedure: { kind: 'star', ident: 'BASI8A', transition: 'BASIP', sequence: 30 },
        }),
      ),
    ).toEqual({
      type: 'procedure_leg',
      airport_icao: 'LFMN',
      kind: 'star',
      ident: 'BASI8A',
      transition: 'BASIP',
      sequence: 30,
    });
  });
});

describe('the Airwork and Custom tabs', () => {
  it('sends the airport’s own coordinate at the chosen level', () => {
    expect(buildPlacementRequest(inputs({ activeTab: 'airwork' }))).toEqual({
      type: 'coordinate',
      position: { latitude: 43.6584, longitude: 7.2159, altitude_ft: 10000 },
      heading_deg: 40,
    });
  });

  it('sends the custom coordinate verbatim', () => {
    expect(buildPlacementRequest(inputs({ activeTab: 'custom' }))).toEqual({
      type: 'coordinate',
      position: { latitude: 43.5, longitude: 7.1, altitude_ft: 3000 },
      heading_deg: 90,
    });
  });

  it('needs neither a runway nor a marker', () => {
    expect(
      buildPlacementRequest(inputs({ activeTab: 'custom', runwayIdent: null })),
    ).not.toBeNull();
  });

  it('needs no airport either — the Map hands over a coordinate and nothing else', () => {
    // docs/designs/instructor-map.md D5: "Send to Position tab" is one of the two commit
    // paths, and the point it hands over is frequently nowhere near a field.
    expect(
      buildPlacementRequest(inputs({ activeTab: 'custom', icao: '', runwayIdent: null })),
    ).toEqual({
      type: 'coordinate',
      position: { latitude: 43.5, longitude: 7.1, altitude_ft: 3000 },
      heading_deg: 90,
    });
  });

  it('answers null rather than a coordinate when the custom position does not resolve', () => {
    expect(
      buildPlacementRequest(inputs({ activeTab: 'custom', custom: null })),
    ).toBeNull();
  });

  it('still lets a selected stand win, and still needs an airport for one', () => {
    expect(
      buildPlacementRequest(inputs({ activeTab: 'custom', standName: 'A3', icao: '' })),
    ).toBeNull();
  });
});

describe('the finals table', () => {
  it('labels and measures every final the server serves', () => {
    for (const name of FINAL_ORDER) {
      expect(FINAL_LABELS[name]).toBeTruthy();
      expect(FINAL_DISTANCE_NM[name]).toBeGreaterThan(0);
    }
    expect(FINAL_ORDER).toHaveLength(7);
  });

  it('is ordered longest first, the order an approach is flown', () => {
    const distances = FINAL_ORDER.map((name) => FINAL_DISTANCE_NM[name]);
    expect([...distances].sort((a, b) => b - a)).toEqual(distances);
  });
});
