/**
 * The two small pure functions that sit between the slice and the server.
 *
 * Building the request is trivial, but it is the one place that decides "no edits" means
 * `setup: null`, not `setup: {}` — sending an empty object would be indistinguishable from a
 * request that means it (weather-manager.md D3: `[]` for a layer list is a real command,
 * `null` is "untouched"), so an accidental `{}` must never reach the wire.
 *
 * `mergeForDisplay` exists because a resolved `WeatherSetup` is deliberately sparse
 * (weather-manager.md D2: a preset states only what it touches, so `cavok` then `crosswind`
 * compose). What the staging surface must show is the *effect* of applying it: the current
 * weather with only the touched fields replaced — never a re-implementation of
 * `core.weather.presets.resolve_request`, which needs navdata this module never has.
 */

import type { WeatherPresetId, WeatherRequest, WeatherSetup, WeatherState } from '../../api/models';

/** The request `preview`/`apply` share: a preset, the instructor's overlay, and the runway context. */
export function buildWeatherRequest(
  presetId: WeatherPresetId,
  overrides: WeatherSetup,
  selectedIcao: string | null,
  selectedRunwayIdent: string | null,
): WeatherRequest {
  return {
    preset: presetId,
    airport_icao: selectedIcao,
    runway_ident: selectedRunwayIdent,
    setup: Object.keys(overrides).length === 0 ? null : overrides,
  };
}

/**
 * What the staged weather would look like once applied: the current weather with every field
 * the resolved setup actually touched replacing it, everything else unchanged.
 *
 * Dewpoint is re-clamped to temperature after the merge — the same invariant
 * `core.weather.models.WeatherState` enforces server-side, needed here because the two can
 * arrive from different sources (a current dewpoint next to a newly staged, lower temperature).
 */
export function mergeForDisplay(current: WeatherState, setup: WeatherSetup): WeatherState {
  const temperature_c = setup.temperature_c ?? current.temperature_c;
  const dewpoint_c = Math.min(setup.dewpoint_c ?? current.dewpoint_c, temperature_c);
  return {
    wind_layers: setup.wind_layers ?? current.wind_layers,
    cloud_layers: setup.cloud_layers ?? current.cloud_layers,
    visibility_m: setup.visibility_m ?? current.visibility_m,
    qnh_hpa: setup.qnh_hpa ?? current.qnh_hpa,
    temperature_c,
    dewpoint_c,
    precipitation_ratio: setup.precipitation_ratio ?? current.precipitation_ratio,
    runway_contamination: setup.runway_contamination ?? current.runway_contamination,
  };
}

/**
 * The request for manual mode: no preset, just the instructor's own overlay. WS-2: manual
 * mode never calls `/preview`, so there is no runway/preset context to resolve — this is a
 * straight passthrough, unlike `buildWeatherRequest`. The caller (`WeatherPanel.tsx`) is
 * responsible for never invoking this with an empty `overrides` (that would 422 server-side,
 * since `WeatherRequest` requires a preset, a setup, or both).
 */
export function buildManualWeatherRequest(overrides: WeatherSetup): WeatherRequest {
  return { preset: null, airport_icao: null, runway_ident: null, setup: overrides };
}
