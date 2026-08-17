/**
 * Display formatting for weather values.
 *
 * Locale pinned to `en-US`, as in `features/telemetry/format.ts`: the readout must be
 * identical on the tablet, the desktop and CI regardless of system locale. All of these
 * render into mono, tabular-nums spans (see `weather.css`).
 *
 * Two unit conversions live here because the wire model and the instructor's reading of it
 * are deliberately different (weather-manager.md D13, D11):
 *
 * - `WindLayer.gust_increase_kt` is the increase *above* the sustained speed ("20 kt gusting
 *   30" is `speed_kt=20, gust_increase_kt=10`); the readout shows the peak, "G 30 kt".
 * - `CloudLayer.coverage_ratio` is a 0-1 float; octas are display-only, never stored.
 */

import type { CloudLayer, RunwayContamination, WeatherState, WindLayer } from '../../api/models';

const INTEGER = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

const METRES_PER_STATUTE_MILE = 1609.344;

/** `250°`, always three digits, normalised to 0–359. */
export function formatDirection(degrees: number): string {
  const normalised = ((Math.round(degrees) % 360) + 360) % 360;
  return `${String(normalised).padStart(3, '0')}°`;
}

/**
 * `250° / 12 kt`, with ` G 22 kt` appended when the layer gusts (the PEAK, `speed_kt +
 * gust_increase_kt`, not the wire field itself); `calm` at 0 kt.
 */
export function formatWind(layer: WindLayer): string {
  if (Math.round(layer.speed_kt) === 0 && Math.round(layer.gust_increase_kt) === 0) {
    return 'calm';
  }
  const steady = `${formatDirection(layer.direction_deg)} / ${INTEGER.format(layer.speed_kt)} kt`;
  if (layer.gust_increase_kt <= 0) {
    return steady;
  }
  const peak = layer.speed_kt + layer.gust_increase_kt;
  return `${steady} G ${INTEGER.format(peak)} kt`;
}

/**
 * Metres first, statute miles beside them: `800 m · 0.5 SM`, `10 km+ · 6.2 SM`. 10 km is the
 * top of the scale, as in a METAR's 9999.
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

/** A 0-1 coverage ratio, on the 0-8 octa scale instructors actually think in. */
export function ratioToOctas(ratio: number): number {
  return Math.round(Math.min(1, Math.max(0, ratio)) * 8);
}

export function octasToRatio(octas: number): number {
  return Math.min(8, Math.max(0, octas)) / 8;
}

/** METAR coverage group for a 0-1 ratio: 0 SKC, 1–2 FEW, 3–4 SCT, 5–7 BKN, 8 OVC. */
export function coverageGroup(ratio: number): string {
  const octas = ratioToOctas(ratio);
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

/** `OVC 200–2,500 ft` — group, base and tops in ft MSL. */
export function formatCloudLayer(layer: CloudLayer): string {
  const base = INTEGER.format(Math.round(layer.base_ft));
  const tops = INTEGER.format(Math.round(layer.tops_ft));
  return `${coverageGroup(layer.coverage_ratio)} ${base}–${tops} ft`;
}

/** The lowest layer stands for the sky in one-line summaries; `sky clear` without one. */
export function formatCloudSummary(state: WeatherState): string {
  const lowest = [...state.cloud_layers].sort((a, b) => a.base_ft - b.base_ft)[0];
  if (lowest === undefined) {
    return 'sky clear';
  }
  const more = state.cloud_layers.length - 1;
  const line = formatCloudLayer(lowest);
  return more > 0 ? `${line} +${more}` : line;
}

/** `none` at 0, otherwise the 0-1 ratio as a percentage: `40%`. */
export function formatPrecipitation(ratio: number): string {
  return ratio <= 0 ? 'none' : `${String(Math.round(ratio * 100))}%`;
}

const CONTAMINATION_LABELS: Record<RunwayContamination, string> = {
  dry: 'Dry',
  wet: 'Wet',
  puddles: 'Puddles',
  snow: 'Snow',
  ice: 'Ice',
};

export function formatContamination(contamination: RunwayContamination): string {
  return CONTAMINATION_LABELS[contamination];
}
