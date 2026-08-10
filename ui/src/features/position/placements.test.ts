/**
 * The placement catalogue and its formatters.
 *
 * Two separate jobs, and both are quietly load-bearing:
 *
 * - The **catalogue** is what stops the panel falling behind the server. A placement added
 *   in `core/geodesy.py` must reach the grid, and the grid must not offer one the server
 *   has never heard of. The exhaustiveness check below is a compile-time assertion as much
 *   as a runtime one: `Record<RunwayPlacementName, true>` does not compile until every
 *   member of the OpenAPI enum is named.
 * - The **formatters** are where a unit gets lost. `formatRunwayLength` is the only metre →
 *   foot conversion on this side of the wire, so it is pinned against a length whose answer
 *   is a known constant rather than against whatever the function happens to return.
 */

import { describe, expect, it } from 'vitest';
import type { RunwayPlacementName } from '../../api/models';
import {
  ALL_RUNWAY_PLACEMENTS,
  FINAL_TILES,
  PATTERN_TILES,
  formatAltitudeFt,
  formatIlsFrequency,
  formatRunwayLength,
  formatSpeedKt,
} from './placements';

/**
 * Every placement the server publishes, spelled out so TypeScript enforces the coverage.
 *
 * This is not a hand-written API type: the *keys* are checked against the generated enum,
 * so adding `final_25nm` on the server breaks this file until the grid gains a tile.
 */
const EVERY_PLACEMENT: Record<RunwayPlacementName, true> = {
  final_20nm: true,
  final_15nm: true,
  final_10nm: true,
  final_8nm: true,
  final_5nm: true,
  final_3nm: true,
  short_final: true,
  left_upwind: true,
  left_crosswind: true,
  left_downwind: true,
  left_base: true,
  right_upwind: true,
  right_crosswind: true,
  right_downwind: true,
  right_base: true,
};

describe('the runway placement catalogue', () => {
  it('offers every placement the server publishes, exactly once', () => {
    expect([...ALL_RUNWAY_PLACEMENTS].sort()).toEqual(
      Object.keys(EVERY_PLACEMENT).sort(),
    );
    expect(new Set(ALL_RUNWAY_PLACEMENTS).size).toBe(ALL_RUNWAY_PLACEMENTS.length);
  });

  it('splits cleanly into a finals rail and a circuit grid', () => {
    const finals = FINAL_TILES.map((tile) => tile.name);
    const circuit = PATTERN_TILES.map((tile) => tile.name);

    expect(finals).toHaveLength(7);
    expect(circuit).toHaveLength(8);
    expect(finals.filter((name) => circuit.includes(name))).toEqual([]);
  });

  it('runs the finals longest first, the order an approach is flown', () => {
    expect(FINAL_TILES.map((tile) => tile.name)).toEqual([
      'final_20nm',
      'final_15nm',
      'final_10nm',
      'final_8nm',
      'final_5nm',
      'final_3nm',
      'short_final',
    ]);
  });
});

describe('the circuit grid layout', () => {
  it('puts left-hand legs left of the runway and right-hand legs right of it', () => {
    // The grid is spatial on purpose: an instructor points at where the aeroplane should
    // be. A left-hand leg drawn on the right would be worse than a plain list.
    for (const tile of PATTERN_TILES) {
      expect(tile.cell.column).toBe(tile.name.startsWith('left_') ? 1 : 3);
    }
  });

  it('leaves the middle column free for the runway itself', () => {
    expect(PATTERN_TILES.map((tile) => tile.cell.column)).not.toContain(2);
  });

  it('gives every tile its own cell, so none is drawn on top of another', () => {
    const cells = PATTERN_TILES.map(
      (tile) => `${String(tile.cell.column)}:${String(tile.cell.row)}`,
    );

    expect(new Set(cells).size).toBe(cells.length);
  });

  it('runs each column from the departure end down to the approach end', () => {
    // `core.geodesy` puts crosswind beyond the far end of the runway, downwind abeam its
    // midpoint and base short of the threshold. Rows increase downwards on screen and the
    // runway hint says "approach from below", so base has to be the bottom row of its
    // column or the tile is pointing at the wrong end of the field.
    for (const column of [1, 3]) {
      const inColumn = PATTERN_TILES.filter((tile) => tile.cell.column === column).sort(
        (a, b) => a.cell.row - b.cell.row,
      );

      expect(inColumn.map((tile) => tile.cell.row)).toEqual([1, 2, 3, 4]);
      expect(inColumn.map((tile) => tile.name.replace(/^(left|right)_/, ''))).toEqual([
        'crosswind',
        'upwind',
        'downwind',
        'base',
      ]);
    }
  });
});

describe('formatAltitudeFt', () => {
  it('rounds to the foot and groups thousands', () => {
    // 4184.357192657228 ft is a 3° glidepath 10 NM out. Twelve decimal places of it is
    // noise pretending to be precision.
    expect(formatAltitudeFt(4184.357192657228)).toBe('4,184 ft');
    expect(formatAltitudeFt(1000)).toBe('1,000 ft');
  });

  it('survives an altitude below sea level', () => {
    // Bar Yehuda (LLMZ) sits at -1,266 ft, and a placement below it is legal.
    expect(formatAltitudeFt(-350.6)).toBe('-351 ft');
  });
});

describe('formatSpeedKt', () => {
  it('rounds to the knot', () => {
    expect(formatSpeedKt(119.6)).toBe('120 kt');
    expect(formatSpeedKt(0)).toBe('0 kt');
  });
});

describe('formatRunwayLength', () => {
  it('converts metres to feet with the exact international foot', () => {
    // One nautical mile is 1852 m and 6076.1 ft by definition. A runway length that comes
    // out as 6,076 ft proves the divisor is 0.3048 and not, say, a 1.0936 yard mix-up.
    expect(formatRunwayLength(1852)).toBe('1,852 m · 6,076 ft');
  });

  it('reads a real runway both ways round', () => {
    // LEMD 32L is 4,100 m.
    expect(formatRunwayLength(4100)).toBe('4,100 m · 13,451 ft');
    expect(formatRunwayLength(610)).toBe('610 m · 2,001 ft');
  });
});

describe('formatIlsFrequency', () => {
  it('renders kilohertz as the megahertz an instructor tunes', () => {
    expect(formatIlsFrequency(110300)).toBe('110.30');
    expect(formatIlsFrequency(109100)).toBe('109.10');
  });

  it('keeps the odd 50 kHz channel', () => {
    // The localiser band is spaced at 50 kHz, so 111.95 must not round to 111.9 or 112.0.
    expect(formatIlsFrequency(111950)).toBe('111.95');
  });
});
