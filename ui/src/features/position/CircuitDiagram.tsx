/**
 * The 720×520 circuit diagram. Pure props → SVG, no store access.
 *
 * The runway, centreline, ticks and downwind/base legs are drawn **unrotated**, in local
 * coordinates (`place(u, v, 0)`), inside one `<g transform="rotate(courseDeg CX CY)">` —
 * exactly like the source: the group's rotation is what orients the picture, not the maths.
 * The wind arrow rotates around its own anchor, outside that group; the north arrow never
 * rotates at all.
 *
 * Every marker dot is drawn twice: once as an SVG circle (visual, `aria-hidden`) inside the
 * rotated group, and once as a real, transparent 44×44 `<button>` absolutely positioned at
 * its fully-resolved screen coordinate (`place(u, v, courseDeg)` — the rotation baked in, so
 * it lines up with the SVG dot without needing to live inside the SVG's own transform). The
 * button is what carries the click handler, the accessible name and the ≥44 px touch target
 * CLAUDE.md asks for; the SVG circle is what carries the visual ring and glow.
 */

import { CX, CY, centrelineTicks, place, windArrowRotation } from './circuit';
import { CIRCUIT_MARKERS, labelPlacement } from './markers';
import { MARKER_IDS, type MarkerId } from './positionDesignSlice';

const TICK_FROM_NM = -10;
const TICK_TO_NM = 2;
const WIND_ANCHOR = { x: 664, y: 74 };
const NORTH_ANCHOR = { x: 46, y: 470 };

function labelOffset(anchor: ReturnType<typeof labelPlacement>): {
  dx: number;
  dy: number;
  textAnchor: 'start' | 'middle' | 'end';
} {
  switch (anchor) {
    case 'left':
      return { dx: -12, dy: 4, textAnchor: 'end' };
    case 'right':
      return { dx: 12, dy: 4, textAnchor: 'start' };
    case 'above':
      return { dx: 0, dy: -12, textAnchor: 'middle' };
    case 'below':
      return { dx: 0, dy: 18, textAnchor: 'middle' };
  }
}

export function CircuitDiagram({
  courseDeg,
  runwayIdent,
  windDeg,
  windKt,
  selectedMarker,
  onSelectMarker,
}: {
  readonly courseDeg: number;
  readonly runwayIdent: string;
  readonly windDeg: number;
  readonly windKt: number;
  readonly selectedMarker: MarkerId;
  readonly onSelectMarker: (id: MarkerId) => void;
}) {
  const ticks = centrelineTicks(TICK_FROM_NM, TICK_TO_NM, 2);
  const runwayNear = place(0.3, 0, 0);
  const runwayFar = place(-1.8, 0, 0);
  const threshold = place(0, 0, 0);
  const centrelineFar = place(TICK_FROM_NM, 0, 0);
  const centrelineNear = place(TICK_TO_NM, 0, 0);
  const windRotation = windArrowRotation(windDeg);

  return (
    <div className="pos-circuit">
      <svg
        viewBox="0 0 720 520"
        width={720}
        height={520}
        className="pos-circuit__svg"
        role="img"
        aria-label={`Circuit diagram for runway ${runwayIdent}`}
      >
        <g transform={`rotate(${String(courseDeg)} ${String(CX)} ${String(CY)})`}>
          <line
            x1={centrelineFar.x}
            y1={centrelineFar.y}
            x2={centrelineNear.x}
            y2={centrelineNear.y}
            className="pos-circuit__centreline"
          />
          {ticks.map((nm) => {
            const p = place(nm, 0, 0);
            return <circle key={nm} cx={p.x} cy={p.y} r={2} className="pos-circuit__tick" />;
          })}
          <line
            x1={place(-1, -4, 0).x}
            y1={place(-1, -4, 0).y}
            x2={place(-6, -4, 0).x}
            y2={place(-6, -4, 0).y}
            className="pos-circuit__leg"
          />
          <line
            x1={place(-1, 4, 0).x}
            y1={place(-1, 4, 0).y}
            x2={place(-6, 4, 0).x}
            y2={place(-6, 4, 0).y}
            className="pos-circuit__leg"
          />
          <line
            x1={runwayNear.x}
            y1={runwayNear.y}
            x2={runwayFar.x}
            y2={runwayFar.y}
            className="pos-circuit__runway"
          />
          <circle cx={threshold.x} cy={threshold.y} r={5} className="pos-circuit__threshold" />

          {MARKER_IDS.map((id) => {
            const marker = CIRCUIT_MARKERS[id];
            const p = place(marker.u, marker.v, 0);
            const selected = id === selectedMarker;
            const offset = labelOffset(labelPlacement(id, courseDeg));
            return (
              <g key={id} aria-hidden="true">
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={selected ? 7 : 5}
                  className={
                    selected ? 'pos-circuit__marker-dot pos-circuit__marker-dot--selected' : 'pos-circuit__marker-dot'
                  }
                />
                <text
                  x={p.x + offset.dx}
                  y={p.y + offset.dy}
                  textAnchor={offset.textAnchor}
                  className="pos-circuit__marker-label"
                >
                  {marker.label}
                </text>
              </g>
            );
          })}
        </g>

        <g
          transform={`rotate(${String(windRotation)} ${String(WIND_ANCHOR.x)} ${String(WIND_ANCHOR.y)})`}
          className="pos-circuit__wind-arrow"
        >
          <line x1={WIND_ANCHOR.x} y1={WIND_ANCHOR.y - 22} x2={WIND_ANCHOR.x} y2={WIND_ANCHOR.y + 22} />
          <polygon
            points={`${String(WIND_ANCHOR.x - 6)},${String(WIND_ANCHOR.y - 14)} ${String(WIND_ANCHOR.x + 6)},${String(WIND_ANCHOR.y - 14)} ${String(WIND_ANCHOR.x)},${String(WIND_ANCHOR.y - 24)}`}
          />
        </g>
        <text x={WIND_ANCHOR.x} y={WIND_ANCHOR.y + 40} textAnchor="middle" className="pos-circuit__wind-label">
          {windDeg}°/{windKt} kt
        </text>

        <g className="pos-circuit__north">
          <line x1={NORTH_ANCHOR.x} y1={NORTH_ANCHOR.y} x2={NORTH_ANCHOR.x} y2={NORTH_ANCHOR.y - 24} />
          <text x={NORTH_ANCHOR.x} y={NORTH_ANCHOR.y + 14} textAnchor="middle">
            N
          </text>
        </g>
      </svg>

      {MARKER_IDS.map((id: MarkerId) => {
        const marker = CIRCUIT_MARKERS[id];
        const p = place(marker.u, marker.v, courseDeg);
        return (
          <button
            key={id}
            type="button"
            className="pos-circuit__marker-button"
            style={{ left: p.x, top: p.y }}
            aria-pressed={id === selectedMarker}
            onClick={() => {
              onSelectMarker(id);
            }}
          >
            <span className="pos-sr-only">{marker.label}</span>
          </button>
        );
      })}
    </div>
  );
}
