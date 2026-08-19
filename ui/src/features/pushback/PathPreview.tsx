/**
 * A small SVG schematic of the staged manoeuvre — a schematic, not a map (the
 * Position Manager's D16 precedent; no MapLibre here either).
 *
 * Drawn in the aircraft's local frame with the nose up. A nose marker sits at the start
 * pointing up, and another at the target rotated by the signed angle — D5 made visible:
 * "right" bends the nose marker clockwise.
 *
 * **Two sources, one drawing, in a deliberate order.** Once the instructor presses
 * Preview, the polyline is the server's own `target.path_preview`, projected nose-up:
 * what is drawn is then literally what `core.pushback` resolved. Before that — while the
 * sliders are still being dragged and nothing has been sent to the simulator — it falls
 * back to `arc.ts`'s client-side arc, so the shape responds live. The two agree by
 * construction (`arc.ts` implements the same closed-form chord identity), which is what
 * makes the swap invisible; the fallback is the decorative one and never outlives a
 * preview.
 */

import type { PushbackDirection, PushbackPreview } from '../../api/models';
import { projectPathLocal, pushbackPathLocal, signedAngleDeg } from './arc';

const VIEW_W = 220;
const VIEW_H = 170;
const PAD = 24;
/** Metres a dimension spans at minimum, so a short straight push is not zoomed absurd. */
const MIN_SPAN_M = 10;

interface PathPreviewProps {
  direction: PushbackDirection;
  distanceM: number;
  angleDeg: number;
  /** The server's resolved preview once it has answered; the arc is a stand-in until then. */
  preview?: PushbackPreview | undefined;
}

export function PathPreview({
  direction,
  distanceM,
  angleDeg,
  preview,
}: PathPreviewProps) {
  const path =
    preview === undefined
      ? pushbackPathLocal(direction, distanceM, angleDeg)
      : projectPathLocal(
          preview.target.path_preview,
          preview.current_position,
          preview.current_heading_deg,
        );

  const xs = path.map((p) => p.x);
  const ys = path.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const scale = Math.min(
    (VIEW_W - 2 * PAD) / Math.max(maxX - minX, MIN_SPAN_M),
    (VIEW_H - 2 * PAD) / Math.max(maxY - minY, MIN_SPAN_M),
  );
  const midX = (minX + maxX) / 2;
  const midY = (minY + maxY) / 2;

  // Local frame to screen: +y is the nose and points up, so screen y flips.
  const toSvg = (p: { x: number; y: number }) => ({
    sx: VIEW_W / 2 + (p.x - midX) * scale,
    sy: VIEW_H / 2 - (p.y - midY) * scale,
  });

  const points = path
    .map((p) => {
      const { sx, sy } = toSvg(p);
      return `${sx.toFixed(1)},${sy.toFixed(1)}`;
    })
    .join(' ');

  // The path always holds points + 1 entries; the fallback only satisfies
  // noUncheckedIndexedAccess.
  const start = toSvg(path.at(0) ?? { x: 0, y: 0 });
  const end = toSvg(path.at(-1) ?? { x: 0, y: 0 });
  const endRotation = signedAngleDeg(direction, angleDeg);

  return (
    <svg
      className="pushback-preview"
      viewBox={`0 0 ${String(VIEW_W)} ${String(VIEW_H)}`}
      role="img"
      aria-label={`Pushback path schematic, nose ${direction}`}
    >
      <polyline className="pushback-preview__path" points={points} />
      <g
        className="pushback-preview__nose pushback-preview__nose--start"
        transform={`translate(${start.sx.toFixed(1)} ${start.sy.toFixed(1)})`}
      >
        <polygon points="0,-7 5,5 -5,5" />
      </g>
      <g
        className="pushback-preview__nose pushback-preview__nose--end"
        transform={`translate(${end.sx.toFixed(1)} ${end.sy.toFixed(1)}) rotate(${endRotation.toFixed(1)})`}
      >
        <polygon points="0,-7 5,5 -5,5" />
      </g>
    </svg>
  );
}
