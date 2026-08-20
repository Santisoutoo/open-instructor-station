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
 *
 * **The buttons are positioned in percentages of the container, never in viewBox pixels.**
 * The SVG scales down (`.pos-circuit` is `width: 720px; max-width: 100%`), so on any viewport
 * narrower than 720 px of diagram — every tablet — a button placed at a raw viewBox
 * coordinate drifts away from the dot it is supposed to be over: at 1024 px the drawing is at
 * ~0.71 and the furthest marker's hit target sits ~88 px from its circle. `.pos-circuit` is
 * the positioning context and the SVG preserves its aspect ratio, so a percentage tracks the
 * scale for free.
 */

import { CX, CY, centrelineTicks, place, windArrowRotation } from './circuit';
import { CIRCUIT_MARKERS, labelPlacement } from './markers';
import { MARKER_IDS, type MarkerId } from './positionDesignSlice';

/**
 * The extended centreline's far end, in NM before the threshold.
 *
 * 8 NM and not 10: the whole picture rotates about (360, 252) by the runway course, so the
 * far end traces a circle of `(8 - UMID) × K = 192` px around that centre — inside the
 * 720×520 box for every course. At 10 NM the radius is 272 px and the last tick fell outside
 * the viewBox (y = 524 in a 520-tall box) for any runway pointing roughly north or south.
 */
const TICK_FROM_NM = -8;
const TICK_TO_NM = 2;
const VIEWBOX_W = 720;
const VIEWBOX_H = 520;
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
  /** `null` when the commanded weather is unknown or unsupported — no arrow is drawn. */
  readonly windDeg: number | null;
  readonly windKt: number | null;
  readonly selectedMarker: MarkerId;
  readonly onSelectMarker: (id: MarkerId) => void;
}) {
  const ticks = centrelineTicks(TICK_FROM_NM, TICK_TO_NM, 2);
  const runwayNear = place(0.3, 0, 0);
  const runwayFar = place(-1.8, 0, 0);
  const threshold = place(0, 0, 0);
  const centrelineFar = place(TICK_FROM_NM, 0, 0);
  const centrelineNear = place(TICK_TO_NM, 0, 0);
  const windRotation = windDeg === null ? null : windArrowRotation(windDeg);

  return (
    <div className="pos-circuit">
      <svg
        viewBox={`0 0 ${String(VIEWBOX_W)} ${String(VIEWBOX_H)}`}
        width={VIEWBOX_W}
        height={VIEWBOX_H}
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
            return (
              <circle key={nm} cx={p.x} cy={p.y} r={2} className="pos-circuit__tick" />
            );
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
          <circle
            cx={threshold.x}
            cy={threshold.y}
            r={5}
            className="pos-circuit__threshold"
          />

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
                    selected
                      ? 'pos-circuit__marker-dot pos-circuit__marker-dot--selected'
                      : 'pos-circuit__marker-dot'
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

        {windRotation !== null && windDeg !== null && windKt !== null && (
          <>
            <g
              transform={`rotate(${String(windRotation)} ${String(WIND_ANCHOR.x)} ${String(WIND_ANCHOR.y)})`}
              className="pos-circuit__wind-arrow"
            >
              <line
                x1={WIND_ANCHOR.x}
                y1={WIND_ANCHOR.y - 22}
                x2={WIND_ANCHOR.x}
                y2={WIND_ANCHOR.y + 22}
              />
              <polygon
                points={`${String(WIND_ANCHOR.x - 6)},${String(WIND_ANCHOR.y - 14)} ${String(WIND_ANCHOR.x + 6)},${String(WIND_ANCHOR.y - 14)} ${String(WIND_ANCHOR.x)},${String(WIND_ANCHOR.y - 24)}`}
              />
            </g>
            <text
              x={WIND_ANCHOR.x}
              y={WIND_ANCHOR.y + 40}
              textAnchor="middle"
              className="pos-circuit__wind-label"
            >
              {String(Math.round(windDeg)).padStart(3, '0')}°/{Math.round(windKt)} kt
            </text>
          </>
        )}

        <g className="pos-circuit__north">
          <line
            x1={NORTH_ANCHOR.x}
            y1={NORTH_ANCHOR.y}
            x2={NORTH_ANCHOR.x}
            y2={NORTH_ANCHOR.y - 24}
          />
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
            style={{
              left: `${String((p.x / VIEWBOX_W) * 100)}%`,
              top: `${String((p.y / VIEWBOX_H) * 100)}%`,
            }}
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
