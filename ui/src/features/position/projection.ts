/**
 * Fitting the server's runway-local frame into the schematic's viewBox.
 *
 * The only maths on this side of the wire. Every point arrives already projected —
 * `x_nm` along the centreline, `y_nm` across it — so all that is left is choosing a scale
 * and an origin. The flat-earth question that makes such a frame unusable for *positioning*
 * was answered on the server, where the geodesy lives; here it only draws a picture.
 *
 * A file of its own rather than living in `Schematic.tsx` so it can be tested without
 * rendering anything.
 */

/** Drawing box in SVG user units. The aspect ratio suits a wide staging bar. */
export const WIDTH = 320;
export const HEIGHT = 180;

/** Space kept clear inside the box so labels near the edge are not clipped. */
export const PADDING = 22;

export interface Bounds {
  readonly minX: number;
  readonly maxX: number;
  readonly minY: number;
  readonly maxY: number;
}

export interface FramePoint {
  readonly x_nm: number;
  readonly y_nm: number;
}

/**
 * The extent of the drawing, in nautical miles, with a floor on how small it can get.
 *
 * The floor matters. A placement on the threshold itself spans zero nautical miles, and
 * scaling to fit *that* would divide by zero — or, worse, not quite, and magnify a metre
 * of survey noise into half the diagram. One nautical mile is the smallest span worth
 * drawing for an aeroplane.
 *
 * The threshold is always included by clamping the span through the origin, so the runway
 * never falls outside the picture no matter where the placement is.
 */
export function schematicBounds(points: readonly FramePoint[]): Bounds {
  if (points.length === 0) {
    return { minX: -1, maxX: 1, minY: -1, maxY: 1 };
  }
  const xs = points.map((point) => point.x_nm);
  const ys = points.map((point) => point.y_nm);
  // Clamped through the origin, so the runway threshold is always in frame.
  return {
    ...widen(Math.min(...xs, 0), Math.max(...xs, 0), 'X'),
    ...widen(Math.min(...ys, 0), Math.max(...ys, 0), 'Y'),
  };
}

/** The smallest span worth drawing for an aeroplane, in nautical miles. */
const MINIMUM_SPAN_NM = 1;

/** Margin as a fraction of the span, so nothing sits exactly on the frame. */
const MARGIN = 0.1;

/**
 * Grow one axis to at least {@link MINIMUM_SPAN_NM}, then add the margin.
 *
 * The widening is symmetric about the midpoint rather than one-sided, so a placement that
 * is nearly on the threshold stays centred instead of drifting to an edge as it converges.
 */
function widen<A extends 'X' | 'Y'>(
  low: number,
  high: number,
  axis: A,
): { [K in `min${A}` | `max${A}`]: number } {
  const midpoint = (low + high) / 2;
  const half = Math.max(high - low, MINIMUM_SPAN_NM) / 2;
  const padded = half * (1 + MARGIN);
  return {
    [`min${axis}`]: midpoint - padded,
    [`max${axis}`]: midpoint + padded,
  } as { [K in `min${A}` | `max${A}`]: number };
}

/**
 * Project one runway-frame point into SVG user units.
 *
 * The runway axis runs **up** the diagram — increasing `x_nm` means decreasing SVG y —
 * because that is how an approach chart is drawn: threshold near the bottom, the aeroplane
 * arriving from below it.
 *
 * **One scale for both axes.** Using a separate scale per axis would fill the box more
 * neatly and shear the geometry doing it: a 10 NM final has to look ten times longer than
 * a 1 NM one, or the diagram stops answering the question it exists for.
 */
export function projectPoint(
  point: FramePoint,
  bounds: Bounds,
): { readonly x: number; readonly y: number } {
  const spanX = bounds.maxX - bounds.minX;
  const spanY = bounds.maxY - bounds.minY;
  const scale = Math.min((HEIGHT - 2 * PADDING) / spanX, (WIDTH - 2 * PADDING) / spanY);
  const centreX = (bounds.minX + bounds.maxX) / 2;
  const centreY = (bounds.minY + bounds.maxY) / 2;
  return {
    x: WIDTH / 2 + (point.y_nm - centreY) * scale,
    y: HEIGHT / 2 - (point.x_nm - centreX) * scale,
  };
}
