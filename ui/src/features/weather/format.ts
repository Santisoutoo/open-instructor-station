/**
 * Display formatting for weather values.
 *
 * Locale pinned to `en-US`, as in `features/telemetry/format.ts`: the readout must
 * be identical on the tablet, the desktop and CI regardless of system locale. All
 * of these render into mono, tabular-nums spans (see `weather.css`).
 */

import type { CloudLayer, WeatherState, WindLayer } from './types.mock';

const INTEGER = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

const METRES_PER_STATUTE_MILE = 1609.344;

/** `250°`, always three digits, normalised to 0–359. */
export function formatDirection(degrees: number): string {
  const normalised = ((Math.round(degrees) % 360) + 360) % 360;
  return `${String(normalised).padStart(3, '0')}°`;
}

/** `250° / 12 kt`, with ` G 22 kt` appended when the layer gusts; `calm` at 0 kt. */
export function formatWind(layer: WindLayer): string {
  if (Math.round(layer.speed_kt) === 0 && Math.round(layer.gust_kt) === 0) {
    return 'calm';
  }
  const steady = `${formatDirection(layer.direction_deg)} / ${INTEGER.format(layer.speed_kt)} kt`;
  return layer.gust_kt > 0 ? `${steady} G ${INTEGER.format(layer.gust_kt)} kt` : steady;
}

/**
 * Metres first, statute miles beside them: `800 m · 0.5 SM`, `10 km+ · 6.2 SM`.
 * 10 km is the top of the scale, as in a METAR's 9999.
 */
export function formatVisibility(metres: number): string {
  const primary =
    metres >= 10000
      ? '10 km+'
      : metres >= 1000
        ? `${(metres / 1000).toFixed(1)} km`
        : `${INTEGER.format(metres)} m`;
  const statute = metres / METRES_PER_STATUTE_MILE;
  return `${primary} · ${statute < 1 ? statute.toFixed(2) : statute.toFixed(1)} SM`;
}

export function formatQnh(hpa: number): string {
  return `${String(Math.round(hpa))} hPa`;
}

/** `19 °C / 7 °C`, temperature over dewpoint, signed below zero. */
export function formatTempDew(temperatureC: number, dewpointC: number): string {
  return `${Math.round(temperatureC)} °C / ${Math.round(dewpointC)} °C`;
}

/** METAR coverage group for an octa count: 0 SKC, 1–2 FEW, 3–4 SCT, 5–7 BKN, 8 OVC. */
export function coverageGroup(octas: number): string {
  if (octas <= 0) {
    return 'SKC';
  }
  if (octas <= 2) {
    return 'FEW';
  }
  if (octas <= 4) {
    return 'SCT';
  }
  if (octas <= 7) {
    return 'BKN';
  }
  return 'OVC';
}

/** `OVC 200–2,500 ft` — group, base and tops in ft AGL. */
export function formatCloudLayer(layer: CloudLayer): string {
  const base = INTEGER.format(Math.round(layer.base_ft_agl));
  const tops = INTEGER.format(Math.round(layer.tops_ft_agl));
  return `${coverageGroup(layer.coverage_octas)} ${base}–${tops} ft`;
}

/** The lowest layer stands for the sky in one-line summaries; `sky clear` without one. */
export function formatCloudSummary(state: WeatherState): string {
  const lowest = [...state.cloud_layers].sort((a, b) => a.base_ft_agl - b.base_ft_agl)[0];
  if (lowest === undefined) {
    return 'sky clear';
  }
  const more = state.cloud_layers.length - 1;
  const line = formatCloudLayer(lowest);
  return more > 0 ? `${line} +${more}` : line;
}
