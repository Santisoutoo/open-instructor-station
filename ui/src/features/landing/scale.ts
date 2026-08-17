/**
 * Chart plumbing for the hand-rolled SVG charts: linear scales, tick picking, and
 * the polyline builder. Pure functions — the components own only markup.
 */

export interface Scale {
  (value: number): number;
  domainMin: number;
  domainMax: number;
}

/** Linear domain → range map. A degenerate domain pins to the range's midpoint. */
export function linearScale(
  [domainMin, domainMax]: readonly [number, number],
  [rangeMin, rangeMax]: readonly [number, number],
): Scale {
  const span = domainMax - domainMin;
  const scale = ((value: number): number => {
    if (span === 0) {
      return (rangeMin + rangeMax) / 2;
    }
    return rangeMin + ((value - domainMin) / span) * (rangeMax - rangeMin);
  }) as Scale;
  scale.domainMin = domainMin;
  scale.domainMax = domainMax;
  return scale;
}

/** The [min, max] of one numeric channel, padded so the trace never kisses the frame. */
export function paddedExtent(values: readonly number[], padRatio = 0.08): [number, number] {
  let min = Infinity;
  let max = -Infinity;
  for (const value of values) {
    if (value < min) {
      min = value;
    }
    if (value > max) {
      max = value;
    }
  }
  if (min === Infinity) {
    return [0, 1];
  }
  const pad = (max - min || 1) * padRatio;
  return [min - pad, max + pad];
}

/**
 * Round tick values across a domain: a 1/2/5 × 10ⁿ step, ticks on multiples of it.
 * Returns at most `count + 2` ticks, always inside the domain.
 */
export function ticks(min: number, max: number, count = 4): number[] {
  const span = max - min;
  if (span <= 0) {
    return [min];
  }
  const rawStep = span / count;
  const power = Math.floor(Math.log10(rawStep));
  const base = 10 ** power;
  const candidates = [base, 2 * base, 2.5 * base, 5 * base, 10 * base];
  const step = candidates.find((candidate) => candidate >= rawStep) ?? 10 * base;
  const first = Math.ceil(min / step) * step;
  const result: number[] = [];
  for (let value = first; value <= max + step / 1e6; value += step) {
    // Snap away float drift so labels render as "200", not "200.00000000003".
    result.push(Number(value.toFixed(Math.max(0, -power + 1))));
  }
  return result;
}

/** The `points` attribute for an SVG polyline through the samples. */
export function polylinePoints<T>(
  samples: readonly T[],
  x: (sample: T) => number,
  y: (sample: T) => number,
  xScale: Scale,
  yScale: Scale,
): string {
  return samples
    .map((sample) => `${xScale(x(sample)).toFixed(1)},${yScale(y(sample)).toFixed(1)}`)
    .join(' ');
}
