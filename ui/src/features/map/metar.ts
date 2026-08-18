/**
 * METAR-style formatting of the COMMANDED `WeatherState` (instructor-map.md §7.9, D10).
 *
 * This is a *display* of what the instructor has told the simulator the weather is — it is
 * never fetched from the internet and it is not a real-world observation. The Weather
 * Manager's `GET /api/weather` is the single source, and `MetarChip.tsx` is the only
 * consumer; everything here is pure so it can be unit-tested without a store or a fetch.
 *
 * The token grammar follows METAR conventions an instructor already reads fluently:
 *
 *   `27005KT 9999 BKN025 19/07 Q1016`
 *   `27020G30KT CAVOK 19/07 Q1013`
 *
 * with three deliberate deviations from a real report, all inherited from the wire model
 * (weather-manager.md D13):
 *
 * - Wind direction is TRUE degrees and is NOT rounded to the nearest 10 — a crosswind
 *   preset that commanded 273° shows `273`, because showing the commanded value verbatim
 *   is the whole point of the chip.
 * - Cloud bases are feet **MSL** (`CloudLayer.base_ft`'s own unit), whereas a real METAR
 *   cloud group is height AGL. Converting needs the field elevation, which this module
 *   does not have. TODO(#113): the overlays track mounts the chip next to its
 *   reference-airport picker — pass that airport's elevation in and subtract it here.
 * - There is no wind-variability, weather-phenomena or trend group: the wire model does
 *   not command them.
 */

import type { CloudLayer, WeatherState, WindLayer } from '../../api/models';
import { coverageGroup } from '../weather/format';

/** `270` → `270`, `-10` → `350`, `360` → `000`; always three digits. */
function directionToken(degrees: number): string {
  const normalised = ((Math.round(degrees) % 360) + 360) % 360;
  return String(normalised).padStart(3, '0');
}

/** A speed or temperature magnitude, at least two digits: `5` → `05`. */
function twoDigits(value: number): string {
  return String(Math.round(Math.abs(value))).padStart(2, '0');
}

/**
 * The surface wind group from the LOWEST layer: `27005KT`, `27020G30KT` (the gust figure is
 * the PEAK, `speed_kt + gust_increase_kt`, not the wire field itself), `00000KT` when calm
 * or when no layer is stated at all.
 */
export function metarWind(layers: readonly WindLayer[]): string {
  const surface = [...layers].sort((a, b) => a.altitude_ft - b.altitude_ft)[0];
  if (
    surface === undefined ||
    (Math.round(surface.speed_kt) === 0 && Math.round(surface.gust_increase_kt) === 0)
  ) {
    return '00000KT';
  }
  const steady = `${directionToken(surface.direction_deg)}${twoDigits(surface.speed_kt)}`;
  if (surface.gust_increase_kt <= 0) {
    return `${steady}KT`;
  }
  const peak = surface.speed_kt + surface.gust_increase_kt;
  return `${steady}G${twoDigits(peak)}KT`;
}

/** The commanded metres as METAR arithmetic sees them: rounded once, floored at zero. */
function roundedVisibility(metres: number): number {
  return Math.max(0, Math.round(metres));
}

/**
 * Four-digit metres, capped METAR-style: `0800`, `9999` at 10 km and above. The cap is
 * applied to the ROUNDED value, so 9999.7 m reads `9999` — never a five-digit `10000`.
 */
export function metarVisibility(metres: number): string {
  return String(Math.min(9999, roundedVisibility(metres))).padStart(4, '0');
}

/**
 * Cloud groups ascending by base, `BKN025` style — the base in hundreds of feet. Layers
 * whose coverage rounds to zero octas state no cloud and are dropped; no remaining layer
 * reads `SKC`.
 */
export function metarClouds(layers: readonly CloudLayer[]): string {
  const groups = [...layers]
    .sort((a, b) => a.base_ft - b.base_ft)
    .map((layer) => ({ group: coverageGroup(layer.coverage_ratio), layer }))
    .filter(({ group }) => group !== 'SKC')
    .map(
      ({ group, layer }) =>
        `${group}${String(Math.max(0, Math.round(layer.base_ft / 100))).padStart(3, '0')}`,
    );
  return groups.length === 0 ? 'SKC' : groups.join(' ');
}

/** `19/07`, `M03/M07` below zero — signed METAR-style with an `M`, never a minus. */
export function metarTemperatures(temperatureC: number, dewpointC: number): string {
  const token = (celsius: number) =>
    `${Math.round(celsius) < 0 ? 'M' : ''}${twoDigits(celsius)}`;
  return `${token(temperatureC)}/${token(dewpointC)}`;
}

/** `Q1016` — QNH in whole hectopascals, always four digits: 998 hPa reads `Q0998`. */
export function metarQnh(hpa: number): string {
  return `Q${String(Math.round(hpa)).padStart(4, '0')}`;
}

/**
 * The whole chip string: wind, visibility + cloud (collapsed to `CAVOK` when the commanded
 * state earns it — 10 km or more, no cloud group, no precipitation), temperature/dewpoint
 * and QNH. The CAVOK comparison uses the same ROUNDED metres the visibility token does,
 * so 9999.7 m collapses to CAVOK rather than falling between the two.
 */
export function formatMetar(state: WeatherState): string {
  const clouds = metarClouds(state.cloud_layers);
  const cavok =
    roundedVisibility(state.visibility_m) >= 10000 &&
    clouds === 'SKC' &&
    state.precipitation_ratio <= 0;
  const visibilityAndCloud = cavok
    ? 'CAVOK'
    : `${metarVisibility(state.visibility_m)} ${clouds}`;
  return [
    metarWind(state.wind_layers),
    visibilityAndCloud,
    metarTemperatures(state.temperature_c, state.dewpoint_c),
    metarQnh(state.qnh_hpa),
  ].join(' ');
}
