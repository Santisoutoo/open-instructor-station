import { describe, expect, it } from 'vitest';
import { place } from './circuit';
import {
  CIRCUIT_MARKERS,
  isFinalMarker,
  labelPlacement,
  legKindOf,
  markerDistanceNm,
  markerLabel,
} from './markers';
import { MARKER_IDS, type CircuitLegKind, type MarkerId } from './positionDesignSlice';

/** A spread of real runway courses, including the cardinal ones that stress the rotation. */
const COURSES = [0, 40, 90, 180, 220, 315];

/** The values `CIRCUIT_PLACEMENTS` hard-coded before the per-leg distance selector existed. */
const CIRCUIT_DISTANCES: Record<CircuitLegKind, number> = {
  downwind: 4,
  base: 6,
  vectors: 6,
};

describe('CIRCUIT_MARKERS', () => {
  it('has 9 unique ids, each with a defined (u, v)', () => {
    expect(MARKER_IDS).toHaveLength(9);
    expect(new Set(MARKER_IDS).size).toBe(9);
    for (const id of MARKER_IDS) {
      const marker = CIRCUIT_MARKERS[id];
      expect(typeof marker.u).toBe('number');
      expect(typeof marker.v).toBe('number');
    }
  });

  it('carries no altitude and no heading — those are the server’s', () => {
    for (const id of MARKER_IDS) {
      expect(CIRCUIT_MARKERS[id]).not.toHaveProperty('altFt');
      expect(CIRCUIT_MARKERS[id]).not.toHaveProperty('headingOffsetDeg');
    }
  });
});

describe('markerDistanceNm / markerLabel', () => {
  it('reads the two final markers off the tab’s final selector', () => {
    for (const id of ['final-3nm', 'final-8nm'] as const) {
      expect(isFinalMarker(id)).toBe(true);
      expect(markerDistanceNm(id, 'final_10nm', CIRCUIT_DISTANCES)).toBe(10);
      expect(markerLabel(id, 'final_10nm')).toBe('10 NM final');
      expect(markerLabel(id, 'short_final')).toBe('Short final');
    }
  });

  it('reads a circuit marker off its own leg’s selected distance, whatever the final selector says', () => {
    expect(markerDistanceNm('base-left', 'final_20nm', CIRCUIT_DISTANCES)).toBe(6);
    expect(markerDistanceNm('downwind-right', 'final_20nm', CIRCUIT_DISTANCES)).toBe(4);
    expect(
      markerDistanceNm('vectors-left', 'final_20nm', { ...CIRCUIT_DISTANCES, vectors: 8 }),
    ).toBe(8);
    expect(markerLabel('downwind-right', 'final_20nm')).toBe('Downwind right');
  });

  it('puts the threshold at zero', () => {
    expect(markerDistanceNm('takeoff', 'final_3nm', CIRCUIT_DISTANCES)).toBe(0);
  });
});

describe('legKindOf', () => {
  it('is null for the threshold and the two finals', () => {
    expect(legKindOf('takeoff')).toBeNull();
    expect(legKindOf('final-3nm')).toBeNull();
    expect(legKindOf('final-8nm')).toBeNull();
  });

  it('groups left/right the same way for every circuit leg', () => {
    expect(legKindOf('downwind-left')).toBe('downwind');
    expect(legKindOf('downwind-right')).toBe('downwind');
    expect(legKindOf('base-left')).toBe('base');
    expect(legKindOf('base-right')).toBe('base');
    expect(legKindOf('vectors-left')).toBe('vectors');
    expect(legKindOf('vectors-right')).toBe('vectors');
  });
});

describe('labelPlacement', () => {
  // Course 0 keeps the rotation out of the way: x varies purely with cross-track (v) and
  // y purely with along-track (u), so which axis dominates is unambiguous.
  it('picks the outboard side for a cross-track-dominant marker', () => {
    expect(['left', 'right']).toContain(labelPlacement('downwind-left', 0));
    expect(['left', 'right']).toContain(labelPlacement('downwind-right', 0));
  });

  it('picks above/below for an along-track-dominant marker', () => {
    expect(['above', 'below']).toContain(labelPlacement('final-8nm', 0));
  });

  it('always centres vectors markers below, regardless of course', () => {
    for (const course of COURSES) {
      expect(labelPlacement('vectors-left', course)).toBe('below');
      expect(labelPlacement('vectors-right', course)).toBe('below');
    }
  });
});

describe('no marker collisions', () => {
  it('places all 9 markers at distinct screen points for every runway course', () => {
    for (const course of COURSES) {
      const points = MARKER_IDS.map((id: MarkerId) => {
        const marker = CIRCUIT_MARKERS[id];
        const point = place(marker.u, marker.v, course);
        return `${point.x.toFixed(3)}:${point.y.toFixed(3)}`;
      });
      expect(new Set(points).size).toBe(points.length);
    }
  });
});
