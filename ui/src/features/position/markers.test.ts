import { describe, expect, it } from 'vitest';
import { place, RUNWAY_FAR_U } from './circuit';
import {
  CIRCUIT_MARKERS,
  isFinalMarker,
  labelPlacement,
  markerDistanceNm,
  markerLabel,
} from './markers';
import { MARKER_IDS, type MarkerId } from './positionDesignSlice';

/** A spread of real runway courses, including the cardinal ones that stress the rotation. */
const COURSES = [0, 40, 90, 180, 220, 315];

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
      expect(markerDistanceNm(id, 'final_10nm')).toBe(10);
      expect(markerLabel(id, 'final_10nm')).toBe('10 NM final');
      expect(markerLabel(id, 'short_final')).toBe('Short final');
    }
  });

  it('keeps a circuit marker’s own geometry, whatever the final selector says', () => {
    expect(markerDistanceNm('base-left', 'final_20nm')).toBe(6);
    expect(markerDistanceNm('downwind-right', 'final_20nm')).toBe(4);
    expect(markerLabel('downwind-right', 'final_20nm')).toBe('Downwind right');
  });

  it('puts the threshold at zero', () => {
    expect(markerDistanceNm('takeoff', 'final_3nm')).toBe(0);
  });
});

describe('the Take off marker', () => {
  it('pins to the runway pavement bar’s far end, the "cabecera" the approach draws into', () => {
    expect(CIRCUIT_MARKERS.takeoff.u).toBe(RUNWAY_FAR_U);
    expect(CIRCUIT_MARKERS.takeoff.v).toBe(0);
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
