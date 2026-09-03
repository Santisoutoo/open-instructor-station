/**
 * Fitting an airport's real stands and runways into the Start-at popover's 380×300 box.
 *
 * This is **drawing, not geodesy**. Nothing here produces a position: no result of this
 * module is ever sent to the server, and the only thing that reaches it from the diagram is
 * a stand *name*. A stand's coordinate is navdata, the placement it becomes is
 * `ParkingPlacementRequest`, and where the little square sits on screen is a picture.
 *
 * Modelled on the deleted `projection.ts` (which fitted the server's runway-local frame
 * into the staging bar's schematic) and it keeps that module's four rules, because they
 * were right:
 *
 * - **One scale for both axes.** A separate scale per axis fills the box more neatly and
 *   shears the airport doing it — parallel runways stop looking parallel.
 * - **Symmetric widening**, so a cluster of stands stays centred instead of drifting to an
 *   edge as more of them arrive.
 * - **A minimum span**, so an airport with one stand does not divide by zero, or — worse —
 *   nearly divide by zero and magnify a metre of survey noise into half the diagram.
 * - **A margin**, so nothing is drawn on the frame.
 *
 * The one addition is the longitude squeeze. A degree of longitude is shorter than a degree
 * of latitude everywhere but the equator, so plotting raw degrees on equal axes stretches
 * an airport east-west — at 43° N, by a factor of 1.4, which is enough to make a runway
 * diagram unrecognisable. Multiplying longitude by cos(latitude) is the standard
 * equirectangular correction, and at the scale of one aerodrome its own distortion is far
 * below a pixel.
 */

export const DIAGRAM_WIDTH = 380;
export const DIAGRAM_HEIGHT = 300;

/** Space kept clear inside the box so a marker near the edge is not clipped. */
export const DIAGRAM_MARGIN = 16;

/**
 * The smallest extent worth drawing, in degrees of latitude — about 220 m.
 *
 * Smaller than the shortest runway at the smallest airfield, so it only ever engages when
 * the points genuinely coincide.
 */
export const MINIMUM_SPAN_DEG = 0.002;

/** Margin as a fraction of the span, so nothing sits exactly on the frame. */
const WIDEN_RATIO = 0.08;

export interface LatLon {
  readonly latitude: number;
  readonly longitude: number;
}

export interface DiagramBounds {
  readonly minLat: number;
  readonly maxLat: number;
  readonly minLon: number;
  readonly maxLon: number;
  /** cos(mid-latitude): how much a degree of longitude is squeezed at this airport. */
  readonly lonScale: number;
}

export interface DiagramPoint {
  readonly x: number;
  readonly y: number;
}

/** Grow a span to at least `minimum`, symmetrically about its midpoint, then add margin. */
function widen(low: number, high: number, minimum: number): [number, number] {
  const midpoint = (low + high) / 2;
  const half = (Math.max(high - low, minimum) / 2) * (1 + WIDEN_RATIO);
  return [midpoint - half, midpoint + half];
}

/**
 * The extent to draw, from every point the diagram shows — stands and runway ends alike.
 *
 * An empty set answers with a degenerate box around the null island rather than throwing:
 * an airport whose parking is not in the navdata still has to render, it just renders
 * nothing inside the frame.
 */
export function diagramBounds(points: readonly LatLon[]): DiagramBounds {
  if (points.length === 0) {
    return { minLat: -0.001, maxLat: 0.001, minLon: -0.001, maxLon: 0.001, lonScale: 1 };
  }
  const lats = points.map((point) => point.latitude);
  const lons = points.map((point) => point.longitude);
  const midLat = (Math.min(...lats) + Math.max(...lats)) / 2;
  // Never zero: |latitude| < 90 at every aerodrome, and cos(89.9°) is still positive.
  const lonScale = Math.max(Math.cos((midLat * Math.PI) / 180), 1e-6);

  const [minLat, maxLat] = widen(Math.min(...lats), Math.max(...lats), MINIMUM_SPAN_DEG);
  const [minLon, maxLon] = widen(
    Math.min(...lons),
    Math.max(...lons),
    MINIMUM_SPAN_DEG / lonScale,
  );
  return { minLat, maxLat, minLon, maxLon, lonScale };
}

/** How many pixels one degree of latitude is worth, given these bounds. */
function scaleOf(bounds: DiagramBounds): number {
  const spanLat = bounds.maxLat - bounds.minLat;
  const spanLon = (bounds.maxLon - bounds.minLon) * bounds.lonScale;
  return Math.min(
    (DIAGRAM_HEIGHT - 2 * DIAGRAM_MARGIN) / spanLat,
    (DIAGRAM_WIDTH - 2 * DIAGRAM_MARGIN) / spanLon,
  );
}

/**
 * Project one latitude/longitude into the diagram's pixel box.
 *
 * North is up — increasing latitude means decreasing SVG y — because that is how every
 * aerodrome chart an instructor has ever read is drawn.
 */
export function projectLatLon(point: LatLon, bounds: DiagramBounds): DiagramPoint {
  const scale = scaleOf(bounds);
  const centreLat = (bounds.minLat + bounds.maxLat) / 2;
  const centreLon = (bounds.minLon + bounds.maxLon) / 2;
  return {
    x: DIAGRAM_WIDTH / 2 + (point.longitude - centreLon) * bounds.lonScale * scale,
    y: DIAGRAM_HEIGHT / 2 - (point.latitude - centreLat) * scale,
  };
}

/** The subset of a runway record the strip pairing reads. */
export interface RunwayEnd extends LatLonThreshold {
  readonly ident: string;
  readonly opposite_ident?: string | null | undefined;
}

interface LatLonThreshold {
  readonly threshold: LatLon;
}

/** One physical strip: the two ends navdata publishes for it, paired once. */
export interface Strip<R extends RunwayEnd = RunwayEnd> {
  readonly key: string;
  readonly from: R;
  readonly to: R;
}

/**
 * Pair each runway end with its opposite, once.
 *
 * `opposite_ident` is navdata's own answer to "the other end of this strip", so the pairing
 * never has to guess from the numbers. An end whose opposite is not in the index yields no
 * strip: its threshold is still labelled, but no line is invented for it.
 */
export function runwayStrips<R extends RunwayEnd>(
  runways: readonly R[],
): readonly Strip<R>[] {
  const byIdent = new Map(runways.map((runway) => [runway.ident, runway]));
  const seen = new Set<string>();
  const result: Strip<R>[] = [];
  for (const runway of runways) {
    const opposite =
      runway.opposite_ident == null ? undefined : byIdent.get(runway.opposite_ident);
    if (opposite === undefined) {
      continue;
    }
    const key = [runway.ident, opposite.ident].sort().join('/');
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push({ key, from: runway, to: opposite });
  }
  return result;
}

/**
 * The south-west / north-east corners of everything the diagram shows, as MapLibre's
 * `[[west, south], [east, north]]` — or `null` when there is nothing to fit.
 */
export function extentOf(
  points: readonly LatLon[],
): [[number, number], [number, number]] | null {
  if (points.length === 0) {
    return null;
  }
  const lats = points.map((point) => point.latitude);
  const lons = points.map((point) => point.longitude);
  return [
    [Math.min(...lons), Math.min(...lats)],
    [Math.max(...lons), Math.max(...lats)],
  ];
}
