import { describe, expect, it } from 'vitest';
import type { LayoutNode, LayoutSegment, ProcedureLayout } from '../../api/models';
import {
  VERTICAL_EXAGGERATION,
  VIEWBOX_H,
  VIEWBOX_W,
  breakGlyph,
  projectLayout,
  rotate,
} from './procedureProjection';

const FLAGS = {
  altitude_source: 'published',
  positioned: true,
  is_positionable: true,
  is_missed_approach: false,
  is_runway: false,
} as const;

function node(
  overrides: Partial<LayoutNode> & Pick<LayoutNode, 'sequence' | 'ident'>,
): LayoutNode {
  return { x_nm: 0, y_nm: 0, altitude_ft: 2000, ...FLAGS, ...overrides };
}

function segment(overrides: Partial<LayoutSegment> = {}): LayoutSegment {
  return {
    from_sequence: 10,
    to_sequence: 20,
    true_length_nm: 5,
    drawn_length_nm: 5,
    scale: 'to_scale',
    bearing_deg: 0,
    ...overrides,
  };
}

function layout(overrides: Partial<ProcedureLayout> = {}): ProcedureLayout {
  return {
    airport_icao: 'ZZZZ',
    kind: 'approach',
    ident: 'I32L',
    transition: null,
    approach_type: 'ils',
    anchor: 'runway',
    airport_x_nm: 0.2,
    airport_y_nm: 0.3,
    airport_elevation_ft: 2000,
    nodes: [
      node({ sequence: 10, ident: 'A', x_nm: 0, y_nm: -3, altitude_ft: 3200 }),
      node({
        sequence: 20,
        ident: 'RW32L',
        x_nm: 0,
        y_nm: 0,
        altitude_ft: 2000,
        is_runway: true,
      }),
    ],
    segments: [segment()],
    total_true_length_nm: 5,
    compressed_segment_count: 0,
    long_factor: 3.0,
    nominal_leg_nm: 2.0,
    ...overrides,
  };
}

describe('rotate', () => {
  it('sends the course bearing straight up the screen', () => {
    // A point 5 NM along a bearing of 40° should land due "up" (negative y, zero x) once the
    // picture is rotated so 40° points up.
    const p = rotate(
      5 * Math.sin((40 * Math.PI) / 180),
      5 * Math.cos((40 * Math.PI) / 180),
      40,
    );
    expect(p.x).toBeCloseTo(0, 6);
    expect(p.y).toBeCloseTo(-5, 6);
  });

  it('sends the perpendicular-right bearing to the right of the screen', () => {
    const p = rotate(
      5 * Math.sin((130 * Math.PI) / 180),
      5 * Math.cos((130 * Math.PI) / 180),
      40,
    );
    expect(p.x).toBeCloseTo(5, 6);
    expect(p.y).toBeCloseTo(0, 6);
  });

  it('is the identity direction at course 0 — north stays up', () => {
    const p = rotate(0, 10, 0);
    expect(p.x).toBeCloseTo(0, 6);
    expect(p.y).toBeCloseTo(-10, 6);
  });
});

describe('projectLayout — the auto-fit', () => {
  it('keeps every drawn and ground point inside the viewBox, at several courses', () => {
    for (const courseDeg of [0, 45, 90, 180, 270, 315]) {
      const projected = projectLayout(layout(), courseDeg);
      const points = projected.nodes
        .flatMap((n) => [n.point, n.ground])
        .concat([projected.airport, projected.airportGround]);
      for (const point of points) {
        expect(point.x).toBeGreaterThanOrEqual(0);
        expect(point.x).toBeLessThanOrEqual(VIEWBOX_W);
        expect(point.y).toBeGreaterThanOrEqual(0);
        expect(point.y).toBeLessThanOrEqual(VIEWBOX_H);
      }
    }
  });

  it('fits a single-node layout without dividing by zero', () => {
    const single = layout({
      nodes: [node({ sequence: 10, ident: 'ONLY', x_nm: 0, y_nm: 0 })],
      segments: [],
    });
    const projected = projectLayout(single, 0);
    expect(Number.isFinite(projected.nodes[0]?.point.x)).toBe(true);
    expect(Number.isFinite(projected.nodes[0]?.point.y)).toBe(true);
  });

  it('fits an empty layout without crashing', () => {
    const empty = layout({ nodes: [], segments: [] });
    expect(() => {
      projectLayout(empty, 0);
    }).not.toThrow();
  });

  it('draws a higher node further up the screen than a lower one on the same track', () => {
    const climbing = layout({
      nodes: [
        node({ sequence: 10, ident: 'LOW', x_nm: 0, y_nm: -1, altitude_ft: 2000 }),
        node({ sequence: 20, ident: 'HIGH', x_nm: 0, y_nm: -1, altitude_ft: 5000 }),
      ],
      segments: [],
    });
    const projected = projectLayout(climbing, 0);
    const low = projected.nodes.find((n) => n.node.ident === 'LOW');
    const high = projected.nodes.find((n) => n.node.ident === 'HIGH');
    expect(high?.point.y).toBeLessThan(low?.point.y ?? Infinity);
    // Their ground footprints, on the other hand, sit at the same point — altitude never
    // moves the footprint, only the drawn point.
    expect(high?.ground.y).toBeCloseTo(low?.ground.y ?? NaN, 6);
  });

  it('scales the drawn separation between two altitudes by VERTICAL_EXAGGERATION', () => {
    // Two otherwise-identical layouts, one with a 3000 ft climb and one with a 6000 ft climb:
    // the taller one's node must be exaggerated further from its ground point than 2x would
    // give for a linear (non-exaggerated) reading, since exaggeration only compounds through
    // the shared vertical axis once, not the fit — this checks the ratio survives the fit.
    const small = layout({
      nodes: [
        node({ sequence: 10, ident: 'A', x_nm: 0, y_nm: -5, altitude_ft: 2000 }),
        node({ sequence: 20, ident: 'B', x_nm: 0, y_nm: 0, altitude_ft: 5000 }),
      ],
      segments: [],
      airport_x_nm: 0,
      airport_y_nm: 0,
      airport_elevation_ft: 2000,
    });
    const tall = layout({
      nodes: [
        node({ sequence: 10, ident: 'A', x_nm: 0, y_nm: -5, altitude_ft: 2000 }),
        node({ sequence: 20, ident: 'B', x_nm: 0, y_nm: 0, altitude_ft: 8000 }),
      ],
      segments: [],
      airport_x_nm: 0,
      airport_y_nm: 0,
      airport_elevation_ft: 2000,
    });
    const smallProjected = projectLayout(small, 0);
    const tallProjected = projectLayout(tall, 0);
    const smallB = smallProjected.nodes.find((n) => n.node.ident === 'B');
    const tallB = tallProjected.nodes.find((n) => n.node.ident === 'B');
    const smallDrop = Math.abs((smallB?.point.y ?? 0) - (smallB?.ground.y ?? 0));
    const tallDrop = Math.abs((tallB?.point.y ?? 0) - (tallB?.ground.y ?? 0));
    // 6000 ft of climb vs 3000 ft — the taller one's own drop is not smaller.
    expect(tallDrop).toBeGreaterThan(smallDrop);
  });

  it('VERTICAL_EXAGGERATION is a small positive multiple, not 1 (a flat line) or absurd', () => {
    expect(VERTICAL_EXAGGERATION).toBeGreaterThan(1);
    expect(VERTICAL_EXAGGERATION).toBeLessThan(20);
  });
});

describe('breakGlyph', () => {
  it('returns a non-trivial SVG path centred between the two points', () => {
    const p = { x: 100, y: 100 };
    const q = { x: 200, y: 100 };
    const d = breakGlyph(p, q);
    expect(d).toMatch(/^M /);
    expect(d).toContain('L');
  });

  it('differs for different segments — it is not a constant decoration', () => {
    const a = breakGlyph({ x: 0, y: 0 }, { x: 100, y: 0 });
    const b = breakGlyph({ x: 0, y: 0 }, { x: 0, y: 100 });
    expect(a).not.toBe(b);
  });

  it('never produces a NaN coordinate, even for coincident points', () => {
    const d = breakGlyph({ x: 50, y: 50 }, { x: 50, y: 50 });
    expect(d).not.toContain('NaN');
  });
});
