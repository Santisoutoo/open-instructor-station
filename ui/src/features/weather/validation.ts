import type { WeatherState } from '../../api/models';

/** Validate the merged instruction without silently changing the values being sent. */
export function weatherValidationError(state: WeatherState): string | null {
  const range = (value: number, min: number, max = Infinity) =>
    Number.isFinite(value) && value >= min && value <= max;

  if (!range(state.visibility_m, 0))
    return 'Visibility must be a finite value of at least 0 m.';
  if (!range(state.qnh_hpa, 900, 1100)) return 'QNH must be between 900 and 1100 hPa.';
  if (!range(state.temperature_c, -60, 60))
    return 'Temperature must be between −60 and 60 °C.';
  if (!range(state.dewpoint_c, -60, 60)) return 'Dewpoint must be between −60 and 60 °C.';
  if (state.dewpoint_c > state.temperature_c)
    return 'Dewpoint must not exceed temperature.';
  if (!range(state.precipitation_ratio, 0, 1))
    return 'Precipitation must be between 0 and 100%.';
  if (state.wind_layers.length > 3) return 'At most three wind layers are supported.';
  if (state.cloud_layers.length > 3) return 'At most three cloud layers are supported.';

  for (const [index, layer] of state.wind_layers.entries()) {
    const name = `Wind layer ${String(index + 1)}`;
    if (!range(layer.altitude_ft, 0))
      return `${name}: altitude must be at least 0 ft MSL.`;
    if (!range(layer.direction_deg, 0, 360))
      return `${name}: direction must be between 0 and 360° true.`;
    if (!range(layer.speed_kt, 0)) return `${name}: speed must be at least 0 kt.`;
    if (!range(layer.gust_increase_kt, 0))
      return `${name}: gust increase must be at least 0 kt.`;
    if (!range(layer.turbulence_ratio, 0, 1))
      return `${name}: turbulence must be between 0 and 100%.`;
    const previous = state.wind_layers[index - 1];
    if (previous !== undefined && layer.altitude_ft - previous.altitude_ft < 100) {
      return 'Wind layers must ascend with at least 100 ft between altitudes.';
    }
  }

  for (const [index, layer] of state.cloud_layers.entries()) {
    const name = `Cloud layer ${String(index + 1)}`;
    if (!Number.isFinite(layer.base_ft) || !Number.isFinite(layer.tops_ft)) {
      return `${name}: base and tops must be finite altitudes.`;
    }
    if (layer.tops_ft <= layer.base_ft) return `${name}: tops must be above the base.`;
    if (!range(layer.coverage_ratio, 0, 1))
      return `${name}: coverage must be between 0 and 100%.`;
    const previous = state.cloud_layers[index - 1];
    if (previous !== undefined && layer.base_ft - previous.base_ft < 100) {
      return 'Cloud layers must ascend with at least 100 ft between bases.';
    }
  }
  return null;
}
