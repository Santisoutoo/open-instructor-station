/**
 * The staging bar's diagram: a runway, the point the aircraft will be put on, and the
 * glidepath between them.
 *
 * **Pure.** Props in, SVG out — no store, no fetch, no geodesy. Every coordinate arrives
 * already projected into the runway's own frame by the server (`SchematicPoint.x_nm` along
 * the centreline, `y_nm` across it), so the only maths here is fitting that frame into a
 * viewBox — and even that lives in `schematicGeometry.ts`. That is what makes it testable
 * without a browser and what keeps the flat-earth projection question on the side of the
 * wire that can answer it.
 *
 * It is deliberately not a map. MapLibre and OSM tiles are the Instructor Map (issue #19);
 * a placement needs to answer "how far out, which side, how high", and a schematic answers
 * that faster and renders instantly on a tablet.
 */

import type { PlacementSchematic } from '../../api/models';
import { HEIGHT, WIDTH, projectPoint, schematicBounds } from './schematicGeometry';

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
      <circle
        className="schematic__aircraft"
        cx={placementXy.x}
        cy={placementXy.y}
        r={5}
      />
    </svg>
  );
}
