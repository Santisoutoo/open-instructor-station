/**
 * The selected procedure, drawn to scale from the airport. Pure props → SVG + HTML overlay,
 * no store access — the same shape as `CircuitDiagram.tsx`.
 *
 * Three layers share one screen: a ground footprint polyline at the airport's own elevation,
 * a drop line from each node down to its footprint, and the flight path itself running
 * through each node's true (exaggerated) altitude. A node whose altitude is not published
 * (`altitude_source !== 'published'`) draws hollow, so an instructor can tell "this is what
 * the chart says" from "this is this diagram's own best guess" at a glance. A compressed
 * segment gets `breakGlyph`'s zig-zag plus its real length in NM — never just a dashed line,
 * which already means something else here (a leg with no resolved fix).
 *
 * Node buttons follow `CircuitDiagram.tsx`'s technique exactly: a transparent 44×44 `<button>`
 * positioned in container percentages, paired with a purely visual, `aria-hidden` SVG dot —
 * see that file's own docstring for why percentages and not viewBox pixels.
 *
 * **Every text label here is an HTML overlay too, for the same reason `CircuitDiagram.tsx`'s
 * are**: `.pos-procdiagram` fits its available box via `width: min(100%, calc(100cqh * 600 /
 * 380))`, which can squeeze it just as short as `.pos-circuit` was measured at 1366×768 — and
 * SVG `font-size` is a viewBox user unit, scaled down by that same transform. A busy
 * procedure can have 15+ nodes (many more simultaneous labels than the circuit diagram's fixed
 * 8 markers), so unlike there, a node landing near the diagram's right edge is a real
 * possibility (`procedureProjection.ts`'s `fitTransform` centers the projection with only a
 * fixed 32px margin) — `nodeLabelSide()` flips the label to the left rather than letting an
 * HTML span (unclipped, unlike SVG text inside its `<svg>`) bleed past the edge.
 */

import { Fragment } from 'react';
import {
  VERTICAL_EXAGGERATION,
  VIEWBOX_H,
  VIEWBOX_W,
  breakGlyph,
  nodeLabelSide,
  projectLayout,
  type ProcedureLayout,
  type ProjectedNode,
  type ScreenPoint,
} from './procedureProjection';

/** A `left`/`top` percentage pair for an HTML overlay element, from a viewBox point. */
function overlayPosition(p: ScreenPoint): { left: string; top: string } {
  return {
    left: `${String((p.x / VIEWBOX_W) * 100)}%`,
    top: `${String((p.y / VIEWBOX_H) * 100)}%`,
  };
}

function segmentIsDashed(from: ProjectedNode, to: ProjectedNode): boolean {
  return (
    !to.node.positioned || from.node.is_missed_approach || to.node.is_missed_approach
  );
}

/**
 * Whether a node's altitude was invented by this diagram rather than read off the chart or
 * the runway record — both `'published'` and `'runway'` are real, sourced numbers.
 */
function isGuessedAltitude(node: ProjectedNode['node']): boolean {
  return node.altitude_source === 'interpolated' || node.altitude_source === 'unknown';
}

export function ProcedureDiagram({
  layout,
  courseDeg,
  selectedSequence,
  onSelectLeg,
}: {
  readonly layout: ProcedureLayout;
  /** The orienting course — the runway's, when one is known; 0 (north-up) otherwise. */
  readonly courseDeg: number;
  readonly selectedSequence: number | null;
  readonly onSelectLeg: (sequence: number) => void;
}) {
  const projected = projectLayout(layout, courseDeg);
  const bySequence = new Map(
    projected.nodes.map((entry) => [entry.node.sequence, entry]),
  );
  const compressed = layout.segments.filter((segment) => segment.scale === 'compressed');

  return (
    <div className="pos-procdiagram">
      <svg
        viewBox={`0 0 ${String(VIEWBOX_W)} ${String(VIEWBOX_H)}`}
        width={VIEWBOX_W}
        height={VIEWBOX_H}
        className="pos-procdiagram__svg"
        role="img"
        aria-label={`Procedure diagram for ${layout.ident}`}
      >
        <polyline
          points={[
            ...projected.nodes.map((n) => `${String(n.ground.x)},${String(n.ground.y)}`),
          ]
            .concat(
              `${String(projected.airportGround.x)},${String(projected.airportGround.y)}`,
            )
            .join(' ')}
          className="pos-procdiagram__ground"
        />

        {projected.nodes.map(({ node, point, ground }) => (
          <line
            key={`drop-${String(node.sequence)}`}
            x1={point.x}
            y1={point.y}
            x2={ground.x}
            y2={ground.y}
            className="pos-procdiagram__drop"
          />
        ))}

        {layout.segments.map((segment) => {
          const from = bySequence.get(segment.from_sequence);
          const to = bySequence.get(segment.to_sequence);
          if (from === undefined || to === undefined) {
            return null;
          }
          return (
            <line
              key={`${String(segment.from_sequence)}-${String(segment.to_sequence)}`}
              x1={from.point.x}
              y1={from.point.y}
              x2={to.point.x}
              y2={to.point.y}
              className={
                segmentIsDashed(from, to)
                  ? 'pos-procdiagram__path pos-procdiagram__path--dashed'
                  : 'pos-procdiagram__path'
              }
            />
          );
        })}

        {compressed.map((segment) => {
          const from = bySequence.get(segment.from_sequence);
          const to = bySequence.get(segment.to_sequence);
          if (from === undefined || to === undefined) {
            return null;
          }
          return (
            <g
              key={`break-${String(segment.from_sequence)}-${String(segment.to_sequence)}`}
              className="pos-procdiagram__break"
            >
              <path d={breakGlyph(from.point, to.point)} />
            </g>
          );
        })}

        {projected.nodes.map(({ node, point }) => (
          <g key={node.sequence} aria-hidden="true">
            <circle
              cx={point.x}
              cy={point.y}
              r={node.sequence === selectedSequence ? 7 : 5}
              className={[
                'pos-procdiagram__node',
                isGuessedAltitude(node) ? 'pos-procdiagram__node--hollow' : '',
                node.sequence === selectedSequence
                  ? 'pos-procdiagram__node--selected'
                  : '',
              ]
                .filter((name) => name !== '')
                .join(' ')}
            />
          </g>
        ))}

        <g className="pos-procdiagram__airport" aria-hidden="true">
          <circle cx={projected.airport.x} cy={projected.airport.y} r={4} />
        </g>
      </svg>

      {/*
       * Every label below is an HTML overlay (see the module docstring for why), positioned
       * exactly like the node buttons: a percentage of `.pos-procdiagram`.
       */}
      {projected.nodes.map(({ node, point }) => {
        const side = nodeLabelSide(point);
        const selected = node.sequence === selectedSequence;
        // A busy procedure can pack nodes close enough in the 2D projection that every label
        // colliding is a real, measured outcome (confirmed live against LFMN's own BADO8A SID:
        // two waypoints landed ~11–22px apart on screen — genuinely close in the procedure's
        // own geometry, not something a bigger diagram or a smaller font fixes). Showing the
        // altitude only for the selected node halves the simultaneous label count in a dense
        // cluster; the ident stays visible for every node (an instructor still needs to see
        // the route), and the full detail for any node is one click away in the leg table.
        const showAltitude = selected;
        return (
          <Fragment key={node.sequence}>
            <span
              aria-hidden="true"
              className={
                selected
                  ? `pos-procdiagram__node-label pos-procdiagram__node-label--${side} pos-procdiagram__node-label--selected`
                  : `pos-procdiagram__node-label pos-procdiagram__node-label--${side}`
              }
              style={overlayPosition(point)}
            >
              {node.ident}
            </span>
            {showAltitude && (
              <span
                aria-hidden="true"
                className={`pos-procdiagram__node-altitude pos-procdiagram__node-altitude--${side}`}
                style={overlayPosition(point)}
              >
                {String(Math.round(node.altitude_ft))} ft
              </span>
            )}
          </Fragment>
        );
      })}

      {compressed.map((segment) => {
        const from = bySequence.get(segment.from_sequence);
        const to = bySequence.get(segment.to_sequence);
        if (from === undefined || to === undefined) {
          return null;
        }
        const mid: ScreenPoint = {
          x: (from.point.x + to.point.x) / 2,
          y: (from.point.y + to.point.y) / 2,
        };
        return (
          <span
            key={`break-label-${String(segment.from_sequence)}-${String(segment.to_sequence)}`}
            aria-hidden="true"
            className="pos-procdiagram__break-label"
            style={overlayPosition(mid)}
          >
            ↔ {segment.true_length_nm.toFixed(1)} NM
          </span>
        );
      })}

      <span
        aria-hidden="true"
        className="pos-procdiagram__airport-label"
        style={overlayPosition(projected.airport)}
      >
        {layout.airport_icao}
      </span>

      <span
        aria-hidden="true"
        className="pos-procdiagram__legend"
        style={overlayPosition({ x: 12, y: VIEWBOX_H - 12 })}
      >
        vertical ×{String(VERTICAL_EXAGGERATION)} · ⌇ not to scale
      </span>

      {projected.nodes
        .filter(({ node }) => node.is_positionable)
        .map(({ node, point }) => (
          <button
            key={node.sequence}
            type="button"
            className="pos-procdiagram__node-button"
            style={overlayPosition(point)}
            aria-pressed={node.sequence === selectedSequence}
            onClick={() => {
              onSelectLeg(node.sequence);
            }}
          >
            <span className="pos-sr-only">{node.ident}</span>
          </button>
        ))}
    </div>
  );
}
