/**
 * Fitting the server's runway-frame points into an SVG viewBox.
 *
 * Pure arithmetic, and deliberately in its own module rather than beside the component
 * that draws with it: a file that exports both a component and a helper breaks React Fast
 * Refresh, which is why `react-refresh/only-export-components` rejects it. Splitting also
 * makes these two functions testable without rendering anything.
 *
 * **This is not geodesy.** Every coordinate arrives already projected by the server
 * (`SchematicPoint.x_nm` along the centreline, `y_nm` across it). The flat-earth question
 * is settled on the side of the wire that can answer it; the only maths here is scale.
 */

import type { PlacementSchematic } from '../../api/models';

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

/**
 * The extent of the drawing, in nautical miles, with a floor on how small it can get.
 *
 * The floor matters: a placement on the threshold itself spans zero nautical miles, and
 * scaling to fit *that* would divide by zero and, if it did not, would magnify a metre of
 * survey noise into half the diagram.
 */
export function schematicBounds(schematic: PlacementSchematic): Bounds {
  const xs = schematic.points.map((point) => point.x_nm);
  const ys = schematic.points.map((point) => point.y_nm);
  if (xs.length === 0) {
    return { minX: -1, maxX: 1, minY: -1, maxY: 1 };
  }
  const minX = Math.min(...xs, 0);
  const maxX = Math.max(...xs, 0);
  const minY = Math.min(...ys, 0);
  const maxY = Math.max(...ys, 0);
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  // Pad by 10 % so nothing sits exactly on the frame.
  const padX = spanX * 0.1;
  const padY = spanY * 0.1;
  return {
    minX: minX - padX,
    maxX: maxX + padX,
    minY: minY - padY,
    maxY: maxY + padY,
  };
}

/**
 * Project one runway-frame point into SVG user units.
 *
 * The runway axis runs **up** the diagram (decreasing SVG y as x_nm increases), because
 * that is how an approach chart is drawn: the threshold near the bottom, the aeroplane
 * coming from below it. One scale is used for both axes so the geometry is not sheared —
 * a 10 NM final must look ten times longer than a 1 NM one.
 */
export function projectPoint(
  point: { x_nm: number; y_nm: number },
  bounds: Bounds,
): { x: number; y: number } {
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
