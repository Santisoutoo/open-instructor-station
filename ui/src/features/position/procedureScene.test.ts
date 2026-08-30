import { describe, expect, it } from 'vitest';
import type { LayoutNode, LayoutSegment, ProcedureLayout } from '../../api/models';
import { VERTICAL_EXAGGERATION as PROJECTION_VERTICAL_EXAGGERATION } from './procedureProjection';
import {
  DEFAULT_FOV_DEG,
  VERTICAL_EXAGGERATION,
  buildProcedureScene,
} from './procedureScene';

const FEET_PER_NAUTICAL_MILE = 6076.12;

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

function heightNm(altitudeFt: number, referenceFt: number): number {
  return ((altitudeFt - referenceFt) / FEET_PER_NAUTICAL_MILE) * VERTICAL_EXAGGERATION;
}

function distance3(a: readonly number[], b: readonly number[]): number {
  return Math.hypot(a[0]! - b[0]!, a[1]! - b[1]!, a[2]! - b[2]!);
}

describe('buildProcedureScene — node/ground mapping', () => {
  it('maps a node to (x_nm, heightNm(altitude), -y_nm) and (x_nm, 0, -y_nm)', () => {
    const l = layout({
      airport_elevation_ft: 2000,
      nodes: [node({ sequence: 10, ident: 'A', x_nm: 4, y_nm: -7, altitude_ft: 5000 })],
      segments: [],
    });
    const scene = buildProcedureScene(l, 0);
    const a = scene.nodes[0]!;
    expect(a.position[0]).toBeCloseTo(4, 6);
    expect(a.position[1]).toBeCloseTo(heightNm(5000, 2000), 6);
    expect(a.position[2]).toBeCloseTo(7, 6);
    expect(a.ground[0]).toBeCloseTo(4, 6);
    expect(a.ground[1]).toBeCloseTo(0, 6);
    expect(a.ground[2]).toBeCloseTo(7, 6);
  });

  it('altitude-height ordering matches altitude ordering, ground stays at y=0', () => {
    const l = layout({
      airport_elevation_ft: 2000,
      nodes: [
        node({ sequence: 10, ident: 'LOW', x_nm: 0, y_nm: -1, altitude_ft: 2000 }),
        node({ sequence: 20, ident: 'HIGH', x_nm: 0, y_nm: -1, altitude_ft: 5000 }),
      ],
      segments: [],
    });
    const scene = buildProcedureScene(l, 0);
    const low = scene.nodes.find((n) => n.node.ident === 'LOW')!;
    const high = scene.nodes.find((n) => n.node.ident === 'HIGH')!;
    expect(high.position[1]).toBeGreaterThan(low.position[1]);
    expect(low.ground[1]).toBe(0);
    expect(high.ground[1]).toBe(0);
  });
});

describe('buildProcedureScene — geometry is invariant under courseDeg', () => {
  it('nodes, segments, groundPolyline and extents do not change with courseDeg; only cameraPose does', () => {
    const l = layout();
    const courses = [0, 45, 90, 180, 270];
    const scenes = courses.map((c) => buildProcedureScene(l, c));
    const reference = scenes[0]!;
    for (const scene of scenes.slice(1)) {
      expect(scene.nodes).toEqual(reference.nodes);
      expect(scene.segments).toEqual(reference.segments);
      expect(scene.groundPolyline).toEqual(reference.groundPolyline);
      expect(scene.airport).toEqual(reference.airport);
      expect(scene.extents).toEqual(reference.extents);
    }
    // Sanity: the camera pose does actually vary across at least one pair of courses.
    expect(scenes[0]!.cameraPose).not.toEqual(scenes[1]!.cameraPose);
  });
});

describe('buildProcedureScene — camera pose', () => {
  it('honors a pinned courseDeg convention: course 0 places the camera south, looking north', () => {
    const scene = buildProcedureScene(layout(), 0);
    const target = scene.cameraPose.target;
    const position = scene.cameraPose.position;
    expect(position[0]).toBeCloseTo(target[0], 6);
    expect(position[2]).toBeGreaterThan(target[2]);
  });

  it('honors a pinned courseDeg convention: course 90 places the camera west, looking east', () => {
    const scene = buildProcedureScene(layout(), 90);
    const target = scene.cameraPose.target;
    const position = scene.cameraPose.position;
    expect(position[0]).toBeLessThan(target[0]);
    expect(position[2]).toBeCloseTo(target[2], 6);
  });

  it('places the camera far enough to frame the full 3D extents, not just the footprint', () => {
    // A tall, laterally tight climb — an XZ-only radius would badly under-fit this.
    const l = layout({
      airport_elevation_ft: 0,
      nodes: [
        node({ sequence: 10, ident: 'LOW', x_nm: 0, y_nm: 0, altitude_ft: 0 }),
        node({ sequence: 20, ident: 'HIGH', x_nm: 0.1, y_nm: 0.1, altitude_ft: 20000 }),
      ],
      segments: [],
      airport_x_nm: 0,
      airport_y_nm: 0,
    });
    const scene = buildProcedureScene(l, 0);
    const fovRad = (DEFAULT_FOV_DEG * Math.PI) / 180;
    const minDistance = scene.extents.radiusNm / Math.sin(fovRad / 2);
    const actualDistance = distance3(scene.cameraPose.position, scene.cameraPose.target);
    expect(actualDistance).toBeCloseTo(minDistance, 6);
    expect(actualDistance).toBeGreaterThan(scene.extents.radiusNm);
  });
});

describe('buildProcedureScene — extents', () => {
  it('a tall, laterally tight procedure gets a 3D radius, not a near-zero XZ-only one', () => {
    const l = layout({
      airport_elevation_ft: 0,
      nodes: [
        node({ sequence: 10, ident: 'LOW', x_nm: 0, y_nm: 0, altitude_ft: 0 }),
        node({ sequence: 20, ident: 'HIGH', x_nm: 0, y_nm: 0, altitude_ft: 20000 }),
      ],
      segments: [],
      airport_x_nm: 0,
      airport_y_nm: 0,
    });
    const scene = buildProcedureScene(l, 0);
    // heightNm(20000 ft) ~= 16.46 NM; a correct 3D fit must reflect that, not the near-zero
    // lateral spread an XZ-only radius (or the MIN_RADIUS_NM floor) would produce.
    expect(scene.extents.radiusNm).toBeGreaterThan(5);
    expect(scene.extents.maxY).toBeGreaterThan(scene.extents.minY);
  });

  it('does not NaN or produce a zero-radius fit for a single-node layout', () => {
    const single = layout({
      nodes: [node({ sequence: 10, ident: 'ONLY', x_nm: 0, y_nm: 0 })],
      segments: [],
    });
    const scene = buildProcedureScene(single, 0);
    expect(Number.isFinite(scene.extents.radiusNm)).toBe(true);
    expect(scene.extents.radiusNm).toBeGreaterThan(0);
    expect(Number.isFinite(scene.extents.minY)).toBe(true);
    expect(Number.isFinite(scene.extents.maxY)).toBe(true);
  });

  it('does not throw for an empty layout, and yields a positive-radius fit', () => {
    const empty = layout({ nodes: [], segments: [] });
    expect(() => {
      buildProcedureScene(empty, 0);
    }).not.toThrow();
    const scene = buildProcedureScene(empty, 0);
    expect(scene.extents.radiusNm).toBeGreaterThan(0);
  });

  it('handles a node below the airport elevation with a finite, correctly-signed height', () => {
    const l = layout({
      airport_elevation_ft: 2000,
      nodes: [node({ sequence: 10, ident: 'A', x_nm: 1, y_nm: -1, altitude_ft: 1000 })],
      segments: [],
    });
    const scene = buildProcedureScene(l, 0);
    const a = scene.nodes[0]!;
    expect(a.position[1]).toBeLessThan(0);
    expect(Number.isFinite(a.position[1])).toBe(true);
    expect(a.ground[1]).toBe(0);
  });
});

describe('buildProcedureScene — curtain segments', () => {
  it('builds a quad wound fromPath -> toPath -> toGround -> fromGround', () => {
    const l = layout();
    const scene = buildProcedureScene(l, 0);
    const seg = scene.segments[0]!;
    expect(seg.curtain).toEqual([seg.from.position, seg.to.position, seg.to.ground, seg.from.ground]);
  });

  it('produces no NaN for a zero-length (coincident) segment', () => {
    const l = layout({
      nodes: [
        node({ sequence: 10, ident: 'A', x_nm: 2, y_nm: -2, altitude_ft: 3000 }),
        node({ sequence: 20, ident: 'B', x_nm: 2, y_nm: -2, altitude_ft: 3000 }),
      ],
      segments: [segment({ from_sequence: 10, to_sequence: 20 })],
    });
    const scene = buildProcedureScene(l, 0);
    const seg = scene.segments[0]!;
    for (const corner of seg.curtain) {
      for (const component of corner) {
        expect(Number.isNaN(component)).toBe(false);
      }
    }
  });

  it('skips a segment referencing a missing sequence instead of throwing', () => {
    const l = layout({
      nodes: [node({ sequence: 10, ident: 'A' })],
      segments: [segment({ from_sequence: 10, to_sequence: 999 })],
    });
    expect(() => {
      buildProcedureScene(l, 0);
    }).not.toThrow();
    const scene = buildProcedureScene(l, 0);
    expect(scene.segments).toHaveLength(0);
  });
});

describe('VERTICAL_EXAGGERATION sharing', () => {
  it('re-exports the exact same VERTICAL_EXAGGERATION as procedureProjection.ts', () => {
    expect(VERTICAL_EXAGGERATION).toBe(PROJECTION_VERTICAL_EXAGGERATION);
  });

  it('computed scene height for a known altitude matches the documented formula', () => {
    const l = layout({
      airport_elevation_ft: 1000,
      nodes: [node({ sequence: 10, ident: 'A', x_nm: 0, y_nm: 0, altitude_ft: 7000 })],
      segments: [],
    });
    const scene = buildProcedureScene(l, 0);
    const expected = ((7000 - 1000) / FEET_PER_NAUTICAL_MILE) * VERTICAL_EXAGGERATION;
    expect(scene.nodes[0]!.position[1]).toBeCloseTo(expected, 6);
  });
});
