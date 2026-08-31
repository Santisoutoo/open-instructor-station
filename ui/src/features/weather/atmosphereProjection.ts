/**
 * Pure projection maths for the atmosphere profile — `procedureProjection.ts`'s idiom: exported
 * constants and pure functions only, no React, no store access.
 *
 * One linear ft-MSL vertical scale carries both wind layers and cloud tops so they read off the
 * same axis (`computeAltitudeScale`). `altitudeToY`/`yToAltitude` are exact inverses of each
 * other — the component draws with the first and a drag reads the pointer back with the second.
 *
 * The three `moveX` helpers are the emit-boundary clamp: called both while drawing a live drag
 * preview and again at commit time with the same final value, so the preview the instructor sees
 * mid-drag never disagrees with what actually gets sent.
 */

import type { CloudLayer, WindLayer } from '../../api/models';

/** The diagram's fixed viewBox. */
export const VIEWBOX_W = 400;
export const VIEWBOX_H = 480;

/** WS-3's scale rule: never less than this, however low the highest layer is. */
export const MIN_SCALE_TOP_FT = 10_000;
/** Headroom above the highest wind altitude / cloud tops. */
export const SCALE_TOP_MARGIN_FT = 2_000;
/** Nearest 100 ft — WS-3's drag snap. */
export const SNAP_FT = 100;
/** The schema's "tops_ft must exceed base_ft" floor, as an explicit minimum gap. */
export const MIN_CLOUD_THICKNESS_FT = 100;
/** Scale ticks every 2 000 ft. */
export const TICK_STEP_FT = 2_000;

/** Left-gutter x for wind barbs. */
export const WIND_GUTTER_CX = 36;
/** Cloud bands span this x-range; the rest of the viewBox is margin/labels. */
export const PLOT_X0 = 72;
export const PLOT_X1 = 340;

const INTEGER_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

export interface AltitudeScale {
  readonly topFt: number;
  readonly bottomFt: 0;
}

/**
 * Computed once from both layer lists so cloud tops and wind layers share one axis.
 */
export function computeAltitudeScale(
  windLayers: readonly WindLayer[],
  cloudLayers: readonly CloudLayer[],
): AltitudeScale {
  const highest = Math.max(
    0,
    ...windLayers.map((layer) => layer.altitude_ft),
    ...cloudLayers.map((layer) => layer.tops_ft),
  );
  return { topFt: Math.max(MIN_SCALE_TOP_FT, highest + SCALE_TOP_MARGIN_FT), bottomFt: 0 };
}

/** MSL feet → SVG y (0 ft at the bottom of the viewBox, `scale.topFt` at the top). */
export function altitudeToY(altitudeFt: number, scale: AltitudeScale, viewboxHeightPx: number): number {
  return viewboxHeightPx * (1 - altitudeFt / scale.topFt);
}

/** The exact inverse of {@link altitudeToY} — what a drag reads the pointer position back as. */
export function yToAltitude(yPx: number, scale: AltitudeScale, viewboxHeightPx: number): number {
  return scale.topFt * (1 - yPx / viewboxHeightPx);
}

/** Nearest 100 ft, half-up (2 550 → 2 600). */
export function snapAltitudeFt(altitudeFt: number): number {
  return Math.round(altitudeFt / SNAP_FT) * SNAP_FT;
}

/** `[0, 2000, ..., topFt]`, inclusive, dropping any off-grid remainder above the last tick. */
export function tickAltitudes(scale: AltitudeScale): readonly number[] {
  const lastTick = Math.floor(scale.topFt / TICK_STEP_FT) * TICK_STEP_FT;
  const ticks: number[] = [];
  for (let tick = 0; tick <= lastTick; tick += TICK_STEP_FT) {
    ticks.push(tick);
  }
  return ticks;
}

/**
 * Secondary AGL label, null-tolerant: `null` field elevation means "MSL only", never a
 * fabricated 0-ft ground reference. Also `null` for a tick below the field (an "underground"
 * MSL value has no meaningful AGL reading).
 */
export function aglLabel(altitudeFt: number, fieldElevationFt: number | null): string | null {
  if (fieldElevationFt === null || altitudeFt < fieldElevationFt) {
    return null;
  }
  return `${INTEGER_FORMAT.format(altitudeFt - fieldElevationFt)} ft AGL`;
}

export interface TerrainBand {
  readonly y: number;
  readonly height: number;
}

/**
 * The terrain band's geometry, `null` when there is no field elevation to draw one from.
 * Clamped into the viewBox when the field sits above the scale's own top (a short/clear-sky
 * scale with a high airport) rather than drawing off-canvas.
 */
export function terrainBand(
  fieldElevationFt: number | null,
  scale: AltitudeScale,
  viewboxHeightPx: number,
): TerrainBand | null {
  if (fieldElevationFt === null || fieldElevationFt <= 0) {
    return null;
  }
  const y = Math.max(0, altitudeToY(fieldElevationFt, scale, viewboxHeightPx));
  return { y, height: viewboxHeightPx - y };
}

export interface ProjectedCloudLayer {
  readonly layer: CloudLayer;
  readonly index: number;
  readonly baseY: number;
  readonly topsY: number;
}

export interface ProjectedWindLayer {
  readonly layer: WindLayer;
  readonly index: number;
  readonly y: number;
}

/** Straight map to screen y — no re-sort, `index` is the selection currency. */
export function projectCloudLayers(
  layers: readonly CloudLayer[],
  scale: AltitudeScale,
  viewboxHeightPx: number,
): readonly ProjectedCloudLayer[] {
  return layers.map((layer, index) => ({
    layer,
    index,
    baseY: altitudeToY(layer.base_ft, scale, viewboxHeightPx),
    topsY: altitudeToY(layer.tops_ft, scale, viewboxHeightPx),
  }));
}

/** Straight map to screen y — no re-sort, `index` is the selection currency. */
export function projectWindLayers(
  layers: readonly WindLayer[],
  scale: AltitudeScale,
  viewboxHeightPx: number,
): readonly ProjectedWindLayer[] {
  return layers.map((layer, index) => ({
    layer,
    index,
    y: altitudeToY(layer.altitude_ft, scale, viewboxHeightPx),
  }));
}

/** Snap + clamp a dragged cloud base: never below 0, never within `MIN_CLOUD_THICKNESS_FT` of tops. */
export function moveCloudBase(layer: CloudLayer, rawBaseFt: number): CloudLayer {
  const base = Math.min(
    Math.max(0, snapAltitudeFt(rawBaseFt)),
    layer.tops_ft - MIN_CLOUD_THICKNESS_FT,
  );
  return { ...layer, base_ft: base };
}

/** Snap + clamp a dragged cloud tops: never within `MIN_CLOUD_THICKNESS_FT` of base. */
export function moveCloudTops(layer: CloudLayer, rawTopsFt: number): CloudLayer {
  const tops = Math.max(snapAltitudeFt(rawTopsFt), layer.base_ft + MIN_CLOUD_THICKNESS_FT);
  return { ...layer, tops_ft: tops };
}

/** Snap + clamp a dragged wind layer's altitude: never below 0. */
export function moveWindAltitude(layer: WindLayer, rawAltFt: number): WindLayer {
  const alt = Math.max(0, snapAltitudeFt(rawAltFt));
  return { ...layer, altitude_ft: alt };
}

/**
 * A wind-barb SVG path in a local frame anchored at (0,0), staff pointing "up" (the component
 * rotates the whole group by `direction_deg` so "up" becomes "the direction the wind is FROM").
 * Rounds to the nearest 5 kt; `''` for calm (the component draws a small circle instead).
 */
export function windBarbPath(speedKt: number): string {
  const rounded = Math.round(speedKt / 5) * 5;
  if (rounded <= 0) {
    return '';
  }

  const staffLength = 36;
  const step = 6;
  const segments: string[] = [`M 0 0 L 0 ${String(-staffLength)}`];

  let remaining = rounded;
  let y = -staffLength;

  while (remaining >= 50) {
    segments.push(`M 0 ${String(y)} L 10 ${String(y + 3)} L 0 ${String(y + 6)} Z`);
    y += step;
    remaining -= 50;
  }
  while (remaining >= 10) {
    segments.push(`M 0 ${String(y)} L 10 ${String(y - 4)}`);
    y += step;
    remaining -= 10;
  }
  if (remaining >= 5) {
    segments.push(`M 0 ${String(y)} L 5 ${String(y - 2)}`);
  }

  return segments.join(' ');
}
