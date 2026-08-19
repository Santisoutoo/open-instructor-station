/**
 * A small SVG schematic of the staged manoeuvre — a schematic, not a map (the
 * Position Manager's D16 precedent; no MapLibre here either).
 *
 * Drawn in the aircraft's local frame with the nose up: the arc is computed
 * client-side by `arc.ts` (the `measure.ts` discipline — decorative precision, the
 * exact numbers come from the server's preview once the wiring wave lands). A nose
 * marker sits at the start pointing up, and another at the target rotated by the
 * signed angle — D5 made visible: "right" bends the nose marker clockwise.
 */

import { pushbackPathLocal, signedAngleDeg } from './arc';
import type { PushbackDirection } from './types.mock';

const VIEW_W = 220;
const VIEW_H = 170;
const PAD = 24;
/** Metres a dimension spans at minimum, so a short straight push is not zoomed absurd. */
const MIN_SPAN_M = 10;

interface PathPreviewProps {
  direction: PushbackDirection;
  distanceM: number;
  angleDeg: number;
}

export function PathPreview({ direction, distanceM, angleDeg }: PathPreviewProps) {
  const path = pushbackPathLocal(direction, distanceM, angleDeg);

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
