/**
 * Fixed-scale projection for the 720×520 circuit diagram SVG.
 *
 * Ported verbatim from the v3 source's geometry (design doc, "Circuit geometry"). Unlike the
 * deleted `projection.ts`, this is **not** an auto-fit: the scale (`K`) and centre are fixed
 * constants, and the runway's true course rotates the whole picture via the SVG's own
 * `<g transform="rotate(...)">`, not via this module. `place()` returns screen coordinates in
 * the *unrotated* local frame — callers draw geometry in local coordinates and let the `<g>`
 * rotation orient it, exactly like the source.
 */

/** Pixels per nautical mile. */
export const K = 40;
/** Screen centre of the 720×520 diagram. */
export const CX = 360;
export const CY = 252;
/** Along-track offset (NM) between the geometric centre and the runway threshold. */
export const UMID = -3.2;

export interface ScreenPoint {
  readonly x: number;
  readonly y: number;
}

/**
 * Projects an along-track/cross-track NM pair (`u` negative = before the threshold, `v`
 * negative = left of centreline) to a screen point, rotated by the runway's true course.
 */
export function place(u: number, v: number, courseDeg: number): ScreenPoint {
  const rad = (courseDeg * Math.PI) / 180;
  const dx = v * K;
  const dy = -(u - UMID) * K;
  return {
    x: CX + dx * Math.cos(rad) - dy * Math.sin(rad),
    y: CY + dx * Math.sin(rad) + dy * Math.cos(rad),
  };
}

/** Every 2 NM tick mark along the extended centreline, from `fromNm` to `toNm` inclusive. */
export function centrelineTicks(fromNm: number, toNm: number, stepNm = 2): readonly number[] {
  const count = Math.floor((toNm - fromNm) / stepNm) + 1;
  return Array.from({ length: count }, (_, i) => fromNm + i * stepNm);
}

/** The wind arrow's rotation, anchored at its own point (664, 74) — points downwind. */
export function windArrowRotation(windDeg: number): number {
  return (windDeg + 180) % 360;
}
