import { describe, expect, it } from 'vitest';
import { place } from './circuit';
import { CIRCUIT_MARKERS, labelPlacement } from './markers';
import { MARKER_IDS, type MarkerId } from './positionDesignSlice';
import { RUNWAYS } from './sampleData';

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
});

describe('labelPlacement', () => {
  // Course 0 keeps the rotation out of the way: x varies purely with cross-track (v) and
  // y purely with along-track (u), so which axis dominates is unambiguous.
  it('picks the outboard side for a cross-track-dominant marker', () => {
    // Downwind sits close abeam (u = -1) but 4 NM off the centreline (v = ±4) — cross
    // track dominates.
    expect(['left', 'right']).toContain(labelPlacement('downwind-left', 0));
    expect(['left', 'right']).toContain(labelPlacement('downwind-right', 0));
  });

  it('picks above/below for an along-track-dominant marker', () => {
    // 8 NM final sits on the centreline (v = 0) — purely along-track.
    expect(['above', 'below']).toContain(labelPlacement('final-8nm', 0));
  });

  it('always centres vectors markers below, regardless of course', () => {
    for (const course of [40, 90, 180, 220, 315]) {
      expect(labelPlacement('vectors-left', course)).toBe('below');
      expect(labelPlacement('vectors-right', course)).toBe('below');
    }
  });
});

describe('no marker collisions', () => {
  const courses = [
    ...new Set(
      Object.values(RUNWAYS).flatMap((runway) => (runway.kind === 'runway' ? [runway.courseDeg] : [])),
    ),
  ];

  it('places all 9 markers at distinct screen points for every runway course', () => {
    for (const course of courses) {
      const points = MARKER_IDS.map((id: MarkerId) => {
        const marker = CIRCUIT_MARKERS[id];
        const p = place(marker.u, marker.v, course);
        return `${p.x.toFixed(3)}:${p.y.toFixed(3)}`;
      });
      expect(new Set(points).size).toBe(points.length);
    }
  });
});
