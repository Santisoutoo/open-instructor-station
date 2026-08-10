/**
 * The schematic's projection.
 *
 * Two properties matter and neither is obvious from reading the code: the runway must
 * always be inside the picture, and the two axes must share a scale so a 10 NM final looks
 * ten times longer than a 1 NM one rather than being stretched to fill the box.
 */

import { describe, expect, it } from 'vitest';
import { HEIGHT, WIDTH, projectPoint, schematicBounds } from './projection';

const THRESHOLD = { x_nm: 0, y_nm: 0 };

describe('schematicBounds', () => {
  it('survives an empty diagram instead of dividing by zero', () => {
    expect(schematicBounds([])).toEqual({ minX: -1, maxX: 1, minY: -1, maxY: 1 });
  });

  it('never scales below one nautical mile', () => {
    // A placement on the threshold itself spans nothing; scaling to fit that would
    // magnify a metre of survey noise into half the diagram.
    const bounds = schematicBounds([THRESHOLD, { x_nm: 0.001, y_nm: 0 }]);

    expect(bounds.maxX - bounds.minX).toBeGreaterThanOrEqual(1);
    expect(bounds.maxY - bounds.minY).toBeGreaterThanOrEqual(1);
  });

  it('always contains the threshold, even for a placement far behind it', () => {
    const bounds = schematicBounds([{ x_nm: -20, y_nm: 0 }]);

    expect(bounds.minX).toBeLessThan(-20);
    expect(bounds.maxX).toBeGreaterThanOrEqual(0);
  });
});

describe('projectPoint', () => {
  it('puts the runway axis up the diagram, chart-style', () => {
    const points = [THRESHOLD, { x_nm: 2, y_nm: 0 }];
    const bounds = schematicBounds(points);

    const threshold = projectPoint(THRESHOLD, bounds);
    const departureEnd = projectPoint({ x_nm: 2, y_nm: 0 }, bounds);

    // Further along the runway is *higher* on screen, i.e. a smaller SVG y.
    expect(departureEnd.y).toBeLessThan(threshold.y);
  });

  it('puts a right-hand offset to the right of the centreline', () => {
    const points = [THRESHOLD, { x_nm: 0, y_nm: 1 }];
    const bounds = schematicBounds(points);

    expect(projectPoint({ x_nm: 0, y_nm: 1 }, bounds).x).toBeGreaterThan(
      projectPoint(THRESHOLD, bounds).x,
    );
  });

  it('does not shear the geometry: one scale serves both axes', () => {
    // A square 4 NM box must come out square, not stretched to the viewBox aspect.
    const points = [THRESHOLD, { x_nm: 4, y_nm: 4 }];
    const bounds = schematicBounds(points);
    const origin = projectPoint(THRESHOLD, bounds);
    const alongAxis = projectPoint({ x_nm: 4, y_nm: 0 }, bounds);
    const acrossAxis = projectPoint({ x_nm: 0, y_nm: 4 }, bounds);

    const alongPixels = Math.abs(alongAxis.y - origin.y);
    const acrossPixels = Math.abs(acrossAxis.x - origin.x);

    expect(alongPixels).toBeCloseTo(acrossPixels, 6);
  });

  it('keeps a long final inside the drawing box', () => {
    const points = [THRESHOLD, { x_nm: 2, y_nm: 0 }, { x_nm: -20, y_nm: 0 }];
    const bounds = schematicBounds(points);

    for (const point of points) {
      const { x, y } = projectPoint(point, bounds);
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(WIDTH);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(HEIGHT);
    }
  });
});
