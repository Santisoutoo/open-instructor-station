/**
 * Oblique projection for the to-scale procedure diagram.
 *
 * Unlike `circuit.ts`'s fixed scale, a procedure ranges from a 1 NM base turn to a 60 NM
 * enroute transition — no single constant fits both, so this **auto-fits** a viewBox instead
 * (`fitTransform`). The runway's true course still orients the picture (`rotate`), exactly
 * like `circuit.ts`'s rotated group, except here the rotation has to happen in the maths:
 * an auto-fit needs the *rotated* extent to size the box, so it cannot be deferred to an SVG
 * `<g transform>` the way the fixed-scale circuit diagram defers it.
 *
 * **The vertical axis is shared, not separate.** A node's screen height combines two
 * things on the same axis: its lateral (rotated) position, and its altitude relative to the
 * airport, exaggerated by `VERTICAL_EXAGGERATION` and converted to the same NM-equivalent
 * unit as everything else before the fit ever runs. That is what makes the picture read as
 * one 3D scene rather than a plan view with numbers floating beside it — every node's
 * "ground" point (its plan position, ignoring altitude) and its drawn point (with altitude)
 * are both exposed, so the diagram can draw a footprint and a drop line between them.
 */

import type { LayoutNode, ProcedureLayout } from '../../api/models';

export type { ProcedureLayout };

export interface ScreenPoint {
  readonly x: number;
  readonly y: number;
}

/** The diagram's fixed viewBox — `.pos-procdiagram` scales it down like `.pos-circuit`. */
export const VIEWBOX_W = 600;
export const VIEWBOX_H = 380;

/** How much altitude is stretched relative to distance — printed on the legend verbatim. */
export const VERTICAL_EXAGGERATION = 5;

const FEET_PER_NAUTICAL_MILE = 6076.12;
const FIT_MARGIN_PX = 32;

/**
 * Rotates an (east, north) NM offset so `courseDeg` points up the screen and its right-hand
 * perpendicular points right — the same convention `circuit.ts`'s rotated `<g>` achieves
 * visually, done here in the maths because the auto-fit below needs the rotated extent.
 */
export function rotate(eastNm: number, northNm: number, courseDeg: number): ScreenPoint {
  const rad = (courseDeg * Math.PI) / 180;
  return {
    x: eastNm * Math.cos(rad) - northNm * Math.sin(rad),
    y: -(eastNm * Math.sin(rad) + northNm * Math.cos(rad)),
  };
}

interface Fit {
  readonly scale: number;
  readonly offsetX: number;
  readonly offsetY: number;
}

/** A scale and offset that centres every point inside the viewBox, margin included. */
function fitTransform(
  points: readonly ScreenPoint[],
  viewboxW: number,
  viewboxH: number,
  marginPx: number,
): Fit {
  if (points.length === 0) {
    return { scale: 1, offsetX: viewboxW / 2, offsetY: viewboxH / 2 };
  }
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const scale = Math.min(
    (viewboxW - 2 * marginPx) / spanX,
    (viewboxH - 2 * marginPx) / spanY,
  );
  return {
    scale,
    offsetX: viewboxW / 2 - ((minX + maxX) / 2) * scale,
    offsetY: viewboxH / 2 - ((minY + maxY) / 2) * scale,
  };
}

function applyFit(point: ScreenPoint, fit: Fit): ScreenPoint {
  return { x: point.x * fit.scale + fit.offsetX, y: point.y * fit.scale + fit.offsetY };
}

export interface ProjectedNode {
  readonly node: LayoutNode;
  /** The node's own drawn point — plan position plus its exaggerated altitude offset. */
  readonly point: ScreenPoint;
  /** Its footprint straight below, at the airport's own elevation — no altitude offset. */
  readonly ground: ScreenPoint;
}

export interface ProjectedLayout {
  readonly nodes: readonly ProjectedNode[];
  readonly airport: ScreenPoint;
  readonly airportGround: ScreenPoint;
}

/**
 * Projects a whole layout, oriented on `courseDeg` and auto-fit to the viewBox.
 *
 * The airport sits on its own ground line by definition — its "altitude offset" relative to
 * itself is always zero — so `airport` and `airportGround` coincide; both are exposed so the
 * diagram can draw it the same way it draws every other node without a special case.
 */
export function projectLayout(
  layout: ProcedureLayout,
  courseDeg: number,
): ProjectedLayout {
  const referenceFt = layout.airport_elevation_ft;
  const heightNm = (altitudeFt: number): number =>
    ((altitudeFt - referenceFt) / FEET_PER_NAUTICAL_MILE) * VERTICAL_EXAGGERATION;

  const rawNodes = layout.nodes.map((node) => {
    const ground = rotate(node.x_nm, node.y_nm, courseDeg);
    return {
      node,
      ground,
      point: { x: ground.x, y: ground.y - heightNm(node.altitude_ft) },
    };
  });
  const rawAirportGround = rotate(layout.airport_x_nm, layout.airport_y_nm, courseDeg);

  const everyPoint = rawNodes
    .flatMap((n) => [n.point, n.ground])
    .concat([rawAirportGround]);
  const fit = fitTransform(everyPoint, VIEWBOX_W, VIEWBOX_H, FIT_MARGIN_PX);

  const airportGround = applyFit(rawAirportGround, fit);
  return {
    nodes: rawNodes.map((n) => ({
      node: n.node,
      point: applyFit(n.point, fit),
      ground: applyFit(n.ground, fit),
    })),
    airport: airportGround,
    airportGround,
  };
}

/**
 * A break/zig-zag mark centred on the midpoint of `p`→`q`, perpendicular to the segment —
 * the "this is compressed, not the real distance" cue a plain dashed line would not carry
 * (a fix-less leg is already dashed for an unrelated reason, so the two must look different).
 */
export function breakGlyph(p: ScreenPoint, q: ScreenPoint, sizePx = 14): string {
  const dx = q.x - p.x;
  const dy = q.y - p.y;
  const length = Math.hypot(dx, dy) || 1;
  const ux = dx / length;
  const uy = dy / length;
  const px = -uy;
  const py = ux;
  const mx = (p.x + q.x) / 2;
  const my = (p.y + q.y) / 2;
  const step = sizePx / 4;
  const offsets = [-2, -1, 0, 1, 2] as const;
  const points = offsets.map((i) => {
    const side = i === 0 ? 0 : Math.sign(i);
    return {
      x: mx + ux * i * step + px * side * step,
      y: my + uy * i * step + py * side * step,
    };
  });
  return points
    .map((point, i) => `${i === 0 ? 'M' : 'L'} ${String(point.x)} ${String(point.y)}`)
    .join(' ');
}
