/**
 * The 720×520 circuit diagram. Pure props → SVG + HTML overlay, no store access.
 *
 * The runway, centreline, ticks and downwind/base legs are drawn **unrotated**, in local
 * coordinates (`place(u, v, 0)`), inside one `<g transform="rotate(courseDeg CX CY)">` —
 * exactly like the source: the group's rotation is what orients the picture, not the maths.
 * The wind arrow rotates around its own anchor, outside that group; the north tick mark never
 * rotates at all.
 *
 * Every marker dot is drawn twice: once as an SVG circle (visual, `aria-hidden`) inside the
 * rotated group, and once as a real, transparent 44×44 `<button>` absolutely positioned at
 * its fully-resolved screen coordinate (`place(u, v, courseDeg)` — the rotation baked in, so
 * it lines up with the SVG dot without needing to live inside the SVG's own transform). The
 * button is what carries the click handler, the accessible name and the ≥44 px touch target
 * CLAUDE.md asks for; the SVG circle is what carries the visual ring and glow.
 *
 * **Every text label — marker names, the wind readout, "N" — is an HTML overlay element, not
 * SVG `<text>`, positioned in percentages exactly like the buttons above.** This was proven
 * necessary, not stylistic: `.pos-circuit`'s box can legitimately shrink well below 720×520
 * (e.g. a 1366×768 laptop screen, whose header/runway-strip/tabs/bottom-bar chrome can leave
 * `.pos-main` under 300 px tall), and SVG `font-size` is a *user unit* — it is scaled down by
 * the same viewBox→box transform as the geometry, so a label that reads fine at 720 px wide
 * renders at a few physical pixels once the box is squeezed, however large its CSS `font-size`
 * says. Measured live at 1366×768: a `font-size: 14px` SVG label painted at an **8 px** actual
 * bounding-box height. Moving labels outside the SVG entirely decouples their legibility from
 * how small the diagram itself is ever forced to become — `clamp()` on `vw` (viewport width,
 * not the diagram's own box) is what requirement 5 asked for in the first place.
 */

import { CX, CY, centrelineTicks, place, windArrowRotation } from './circuit';
import { CIRCUIT_MARKERS, DRAWN_MARKER_IDS, labelPlacement } from './markers';
import type { MarkerId } from './positionDesignSlice';

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

/** A `left`/`top` percentage pair for an HTML overlay element, from a viewBox point. */
function overlayPosition(p: { x: number; y: number }): { left: string; top: string } {
  return {
    left: `${String((p.x / VIEWBOX_W) * 100)}%`,
    top: `${String((p.y / VIEWBOX_H) * 100)}%`,
  };
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

          {DRAWN_MARKER_IDS.map((id) => {
            const marker = CIRCUIT_MARKERS[id];
            const p = place(marker.u, marker.v, 0);
            const selected = id === selectedMarker;
            return (
              <circle
                key={id}
                cx={p.x}
                cy={p.y}
                r={selected ? 7 : 5}
                aria-hidden="true"
                className={
                  selected
                    ? 'pos-circuit__marker-dot pos-circuit__marker-dot--selected'
                    : 'pos-circuit__marker-dot'
                }
              />
            );
          })}
        </g>

        {windRotation !== null && windDeg !== null && windKt !== null && (
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
        )}

        <line
          x1={NORTH_ANCHOR.x}
          y1={NORTH_ANCHOR.y}
          x2={NORTH_ANCHOR.x}
          y2={NORTH_ANCHOR.y - 24}
          className="pos-circuit__north"
        />
      </svg>

      {/*
       * Every label below is an HTML overlay (see the module docstring for why), positioned
       * exactly like the marker buttons: a percentage of `.pos-circuit`, from the same
       * `place(u, v, courseDeg)` point the corresponding SVG dot uses.
       */}
      {DRAWN_MARKER_IDS.map((id) => {
        const marker = CIRCUIT_MARKERS[id];
        const p = place(marker.u, marker.v, courseDeg);
        const anchor = labelPlacement(id, courseDeg);
        const selected = id === selectedMarker;
        return (
          <span
            key={id}
            aria-hidden="true"
            className={
              selected
                ? `pos-circuit__marker-label pos-circuit__marker-label--${anchor} pos-circuit__marker-label--selected`
                : `pos-circuit__marker-label pos-circuit__marker-label--${anchor}`
            }
            style={overlayPosition(p)}
          >
            {marker.label}
          </span>
        );
      })}

      {windDeg !== null && windKt !== null && (
        <span
          aria-hidden="true"
          className="pos-circuit__wind-label"
          style={overlayPosition({ x: WIND_ANCHOR.x, y: WIND_ANCHOR.y + 40 })}
        >
          {String(Math.round(windDeg)).padStart(3, '0')}°/{Math.round(windKt)} kt
        </span>
      )}

      <span
        aria-hidden="true"
        className="pos-circuit__north-label"
        style={overlayPosition({ x: NORTH_ANCHOR.x, y: NORTH_ANCHOR.y + 14 })}
      >
        N
      </span>

      {DRAWN_MARKER_IDS.map((id: MarkerId) => {
        const marker = CIRCUIT_MARKERS[id];
        const p = place(marker.u, marker.v, courseDeg);
        return (
          <button
            key={id}
            type="button"
            className="pos-circuit__marker-button"
            style={overlayPosition(p)}
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
