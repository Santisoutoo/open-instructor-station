import type { CloudLayer, WindLayer } from '../../api/models';

export const LAYER_SEPARATION_FT = 100;
export const MAX_LAYERS = 3;

export function altitudeBounds(values: readonly number[], index: number, minimum = 0) {
  return {
    min: index === 0 ? minimum : (values[index - 1] ?? minimum) + LAYER_SEPARATION_FT,
    max:
      index === values.length - 1
        ? Infinity
        : (values[index + 1] ?? Infinity) - LAYER_SEPARATION_FT,
  };
}

export function clampLayerAltitude(
  values: readonly number[],
  index: number,
  value: number,
  minimum = 0,
): number {
  const bounds = altitudeBounds(values, index, minimum);
  return Math.max(bounds.min, Math.min(bounds.max, value));
}

export function windAltitudeBounds(layers: readonly WindLayer[], index: number) {
  return altitudeBounds(
    layers.map((layer) => layer.altitude_ft),
    index,
  );
}

export function cloudBaseBounds(layers: readonly CloudLayer[], index: number) {
  const bounds = altitudeBounds(
    layers.map((layer) => layer.base_ft),
    index,
    -Infinity,
  );
  return {
    min: bounds.min,
    max: Math.min(bounds.max, layers[index]?.tops_ft ?? Infinity),
  };
}

export function nextWindLayer(layers: readonly WindLayer[]): WindLayer | null {
  if (layers.length >= MAX_LAYERS) return null;
  const altitude = layers.length === 0 ? 0 : (layers.at(-1)?.altitude_ft ?? 0) + 2000;
  if (!Number.isFinite(altitude) || altitude <= (layers.at(-1)?.altitude_ft ?? -1))
    return null;
  return {
    altitude_ft: altitude,
    direction_deg: 270,
    speed_kt: 15,
    gust_increase_kt: 0,
    turbulence_ratio: 0,
  };
}

export function nextCloudLayer(layers: readonly CloudLayer[]): CloudLayer | null {
  if (layers.length >= MAX_LAYERS) return null;
  const base =
    layers.length === 0
      ? 3000
      : Math.max(layers.at(-1)?.tops_ft ?? 0, (layers.at(-1)?.base_ft ?? 0) + 100) + 1000;
  if (!Number.isFinite(base) || !Number.isFinite(base + 2000) || base + 2000 <= base)
    return null;
  return {
    base_ft: base,
    tops_ft: base + 2000,
    coverage_ratio: 0.5,
    cloud_type: 'cumulus',
  };
}
