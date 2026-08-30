import { describe, expect, it } from 'vitest';
import {
  DIAGRAM_HEIGHT,
  DIAGRAM_MARGIN,
  DIAGRAM_WIDTH,
  MINIMUM_SPAN_DEG,
  diagramBounds,
  extentOf,
  projectLatLon,
  runwayStrips,
  type LatLon,
} from './standProjection';

const NICE: LatLon = { latitude: 43.6584, longitude: 7.2159 };

function spread(points: readonly LatLon[]) {
  const bounds = diagramBounds(points);
  return points.map((point) => projectLatLon(point, bounds));
}

describe('diagramBounds', () => {
  it('answers with a degenerate box for an airport with nothing to draw', () => {
    const bounds = diagramBounds([]);
    expect(bounds.maxLat).toBeGreaterThan(bounds.minLat);
    expect(bounds.maxLon).toBeGreaterThan(bounds.minLon);
  });

  it('never lets a span collapse below the minimum', () => {
    // Two stands a metre apart: without the floor, the scale would be astronomical.
    const bounds = diagramBounds([NICE, { ...NICE, latitude: NICE.latitude + 0.00001 }]);
    expect(bounds.maxLat - bounds.minLat).toBeGreaterThanOrEqual(MINIMUM_SPAN_DEG);
  });

  it('widens symmetrically, so a tight cluster stays centred', () => {
    const bounds = diagramBounds([NICE]);
    expect((bounds.minLat + bounds.maxLat) / 2).toBeCloseTo(NICE.latitude, 10);
    expect((bounds.minLon + bounds.maxLon) / 2).toBeCloseTo(NICE.longitude, 10);
  });

  it('squeezes longitude by the cosine of the mid-latitude', () => {
    expect(diagramBounds([NICE]).lonScale).toBeCloseTo(
      Math.cos((43.6584 * Math.PI) / 180),
      6,
    );
    expect(diagramBounds([{ latitude: 0, longitude: 0 }]).lonScale).toBeCloseTo(1, 6);
  });
});

describe('projectLatLon', () => {
  it('puts the centre of the extent at the centre of the box', () => {
    const bounds = diagramBounds([NICE]);
    const point = projectLatLon(NICE, bounds);
    expect(point.x).toBeCloseTo(DIAGRAM_WIDTH / 2, 6);
    expect(point.y).toBeCloseTo(DIAGRAM_HEIGHT / 2, 6);
  });

  it('draws north up', () => {
    const points = spread([NICE, { ...NICE, latitude: NICE.latitude + 0.01 }]);
    const [south, north] = points;
    expect(north).toBeDefined();
    expect(south).toBeDefined();
    expect(north?.y).toBeLessThan(south?.y ?? 0);
  });

  it('draws east right', () => {
    const points = spread([NICE, { ...NICE, longitude: NICE.longitude + 0.01 }]);
    const [west, east] = points;
    expect(east?.x).toBeGreaterThan(west?.x ?? 0);
  });

  it('keeps everything inside the margin', () => {
    const points = spread([
      NICE,
      { latitude: NICE.latitude + 0.02, longitude: NICE.longitude + 0.03 },
      { latitude: NICE.latitude - 0.015, longitude: NICE.longitude - 0.01 },
    ]);
    for (const point of points) {
      expect(point.x).toBeGreaterThanOrEqual(DIAGRAM_MARGIN - 1);
      expect(point.x).toBeLessThanOrEqual(DIAGRAM_WIDTH - DIAGRAM_MARGIN + 1);
      expect(point.y).toBeGreaterThanOrEqual(DIAGRAM_MARGIN - 1);
      expect(point.y).toBeLessThanOrEqual(DIAGRAM_HEIGHT - DIAGRAM_MARGIN + 1);
    }
  });

  it('uses ONE scale for both axes, so the airport is not sheared', () => {
    // A square patch on the ground — equal north-south and east-west extent once the
    // longitude squeeze is applied. Laid out symmetrically about NICE so the bounds'
    // mid-latitude, and therefore its squeeze factor, is exactly NICE's own.
    const lonScale = Math.cos((NICE.latitude * Math.PI) / 180);
    const halfLat = 0.01;
    const halfLon = halfLat / lonScale;
    const [south, north, west, east] = spread([
      { latitude: NICE.latitude - halfLat, longitude: NICE.longitude },
      { latitude: NICE.latitude + halfLat, longitude: NICE.longitude },
      { latitude: NICE.latitude, longitude: NICE.longitude - halfLon },
      { latitude: NICE.latitude, longitude: NICE.longitude + halfLon },
    ]);
    const verticalPx = Math.abs((north?.y ?? 0) - (south?.y ?? 0));
    const horizontalPx = Math.abs((east?.x ?? 0) - (west?.x ?? 0));
    expect(horizontalPx).toBeCloseTo(verticalPx, 6);
  });
});

describe('runwayStrips', () => {
  const end = (ident: string, opposite_ident: string | null, latitude: number) => ({
    ident,
    opposite_ident,
    threshold: { latitude, longitude: NICE.longitude },
  });

  it('pairs each end with its opposite exactly once', () => {
    const strips = runwayStrips([end('04R', '22L', 43.65), end('22L', '04R', 43.67)]);
    expect(strips).toHaveLength(1);
    expect(strips[0]?.key).toBe('04R/22L');
  });

  it('invents no strip for an end whose opposite is not in the index', () => {
    expect(runwayStrips([end('04R', '22L', 43.65)])).toHaveLength(0);
    expect(runwayStrips([end('18', null, 43.65)])).toHaveLength(0);
  });
});

describe('extentOf', () => {
  it('is null with nothing to fit, and the SW/NE corners otherwise', () => {
    expect(extentOf([])).toBeNull();
    expect(
      extentOf([
        { latitude: 43.65, longitude: 7.2 },
        { latitude: 43.68, longitude: 7.23 },
      ]),
    ).toEqual([
      [7.2, 43.65],
      [7.23, 43.68],
    ]);
  });
});
