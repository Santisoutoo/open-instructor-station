/**
 * The staging bar's diagram: a runway, the point the aircraft will be put on, and the
 * glidepath between them.
 *
 * **Pure.** Props in, SVG out — no store, no fetch, no geodesy. Every coordinate arrives
 * already projected into the runway's own frame by the server (`SchematicPoint.x_nm` along
 * the centreline, `y_nm` across it), so the only maths here is fitting that frame into a
 * viewBox. That is what makes it testable without a browser and what keeps the flat-earth
 * projection question on the side of the wire that can answer it.
 *
 * It is deliberately not a map. MapLibre and OSM tiles are the Instructor Map (issue #19);
 * a placement needs to answer "how far out, which side, how high", and a schematic answers
 * that faster and renders instantly on a tablet.
 */

import type { PlacementSchematic } from '../../api/models';

/** Drawing box in SVG user units. The aspect ratio suits a wide staging bar. */
const WIDTH = 320;
const HEIGHT = 180;
/** Space kept clear inside the box so labels near the edge are not clipped. */
const PADDING = 22;

interface Bounds {
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

export interface SchematicProps {
  readonly schematic: PlacementSchematic;
  /** True heading the aircraft will face, drawn as a short vector off the placement dot. */
  readonly headingDeg: number;
}

/** The diagram, or `null` when there is nothing runway-relative to draw. */
export function Schematic({ schematic, headingDeg }: SchematicProps) {
  const threshold = schematic.points.find((point) => point.role === 'threshold');
  const runwayEnd = schematic.points.find((point) => point.role === 'runway_end');
  const placement = schematic.points.find((point) => point.role === 'placement');

  if (threshold === undefined || runwayEnd === undefined || placement === undefined) {
    return null;
  }

  const bounds = schematicBounds(schematic);
  const thresholdXy = projectPoint(threshold, bounds);
  const endXy = projectPoint(runwayEnd, bounds);
  const placementXy = projectPoint(placement, bounds);

  // The heading vector is drawn relative to the runway axis, which points up the diagram.
  const relativeDeg = headingDeg - (schematic.runway_true_bearing_deg ?? 0);
  const radians = (relativeDeg * Math.PI) / 180;
  const vectorLength = 18;
  const headingTip = {
    x: placementXy.x + Math.sin(radians) * vectorLength,
    y: placementXy.y - Math.cos(radians) * vectorLength,
  };

  return (
    <svg
      className="schematic"
      viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
      role="img"
      aria-label={`Placement diagram for runway ${schematic.runway_ident ?? 'unknown'}`}
    >
      {/* Extended centreline: where a final lies. Dashed, because it is not pavement. */}
      <line
        className="schematic__centreline"
        x1={thresholdXy.x}
        y1={thresholdXy.y}
        x2={placementXy.x}
        y2={placementXy.y}
      />
      {/* The runway itself, drawn thick so it reads as the one solid object. */}
      <line
        className="schematic__runway"
        x1={thresholdXy.x}
        y1={thresholdXy.y}
        x2={endXy.x}
        y2={endXy.y}
      />
      <text
        className="schematic__label"
        x={thresholdXy.x}
        y={thresholdXy.y + 14}
        textAnchor="middle"
      >
        {schematic.runway_ident ?? ''}
      </text>

      <line
        className="schematic__heading"
        x1={placementXy.x}
        y1={placementXy.y}
        x2={headingTip.x}
        y2={headingTip.y}
      />
      <circle className="schematic__aircraft" cx={placementXy.x} cy={placementXy.y} r={5} />
    </svg>
  );
}
