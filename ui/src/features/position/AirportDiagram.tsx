/**
 * The 340×262 airport diagram in the Start-at popover — drawn from the airport's own
 * navdata: every runway strip between the two thresholds navdata publishes for it, and one
 * clickable square per parking stand at the stand's own coordinate.
 *
 * The projection is in `standProjection.ts` and is pure, so the fitting can be tested
 * without rendering anything. Nothing computed here ever crosses the wire: clicking a
 * square sends the stand's **name**, and the server resolves the position. Nothing here
 * steps a distance along a bearing either — a strip is drawn between two coordinates
 * navdata already published, or it is not drawn at all.
 *
 * The v3 mockup's three shaded terminal blocks are not drawn. `apt.dat` publishes runways,
 * taxiways and parking positions; it does not publish terminal buildings, and three
 * rectangles invented to look like Nice would be decoration masquerading as an aerodrome
 * chart.
 */

import type { ParkingStand, Runway } from '../../api/models';
import {
  DIAGRAM_HEIGHT,
  DIAGRAM_WIDTH,
  diagramBounds,
  projectLatLon,
  type LatLon,
} from './standProjection';

/** One physical strip: the two ends navdata publishes for it, paired once. */
interface Strip {
  readonly key: string;
  readonly from: Runway;
  readonly to: Runway;
}

/**
 * Pair each runway end with its opposite, once.
 *
 * `opposite_ident` is navdata's own answer to "the other end of this strip", so the pairing
 * never has to guess from the numbers. An end whose opposite is not in the index yields no
 * strip: its threshold is still labelled, but no line is invented for it.
 */
function runwayStrips(runways: readonly Runway[]): readonly Strip[] {
  const byIdent = new Map(runways.map((runway) => [runway.ident, runway]));
  const seen = new Set<string>();
  const result: Strip[] = [];
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

export function AirportDiagram({
  stands,
  runways,
  selectedStand,
  onSelect,
}: {
  readonly stands: readonly ParkingStand[];
  readonly runways: readonly Runway[];
  readonly selectedStand: string | null;
  readonly onSelect: (name: string) => void;
}) {
  const strips = runwayStrips(runways);
  const points: readonly LatLon[] = [
    ...stands.map((stand) => stand.position),
    ...runways.map((runway) => runway.threshold),
  ];
  const bounds = diagramBounds(points);

  return (
    <div className="pos-diagram" style={{ width: DIAGRAM_WIDTH, height: DIAGRAM_HEIGHT }}>
      <svg
        viewBox={`0 0 ${String(DIAGRAM_WIDTH)} ${String(DIAGRAM_HEIGHT)}`}
        width={DIAGRAM_WIDTH}
        height={DIAGRAM_HEIGHT}
        className="pos-diagram__svg"
        role="img"
        aria-label="Airport diagram"
      >
        {strips.map((strip) => {
          const a = projectLatLon(strip.from.threshold, bounds);
          const b = projectLatLon(strip.to.threshold, bounds);
          return (
            <line
              key={strip.key}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              className="pos-diagram__runway-line"
            />
          );
        })}
        {runways.map((runway) => {
          const point = projectLatLon(runway.threshold, bounds);
          return (
            <text
              key={runway.ident}
              x={point.x}
              y={point.y}
              textAnchor="middle"
              className="pos-diagram__runway-label"
            >
              {runway.ident}
            </text>
          );
        })}
      </svg>

      {stands.map((stand) => {
        const point = projectLatLon(stand.position, bounds);
        return (
          <button
            key={stand.name}
            type="button"
            className={
              stand.name === selectedStand
                ? 'pos-diagram__stand pos-diagram__stand--selected'
                : 'pos-diagram__stand'
            }
            style={{ left: point.x, top: point.y }}
            aria-pressed={stand.name === selectedStand}
            aria-label={`Stand ${stand.name}`}
            onClick={() => {
              onSelect(stand.name);
            }}
          >
            <span className="pos-diagram__stand-dot" aria-hidden="true" />
          </button>
        );
      })}
    </div>
  );
}
