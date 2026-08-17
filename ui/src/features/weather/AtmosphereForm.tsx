/**
 * The scalar half of the staged weather: QNH, visibility, temperature, dewpoint.
 *
 * The dewpoint can never exceed the temperature. The input's own max moves with the
 * resolved temperature and the write clamps to it; lowering the temperature under
 * the dewpoint is resolved by `resolveWeather`, which clamps on every read — so the
 * invariant holds whatever order the edits arrive in.
 */

import { NumberField } from './NumberField';
import type { WeatherOverrides, WeatherState } from './types.mock';

interface AtmosphereFormProps {
  /** The resolved staged weather — preset + overrides, clamped. */
  resolved: WeatherState;
  disabled: boolean;
  onField: (field: keyof WeatherOverrides, value: number) => void;
}

export function AtmosphereForm({ resolved, disabled, onField }: AtmosphereFormProps) {
  return (
    <fieldset className="weather-group">
      <legend className="weather-group__title">Atmosphere</legend>
      <div className="weather-row">
        <NumberField
          label="QNH"
          unit="hPa"
          value={resolved.qnh_hpa}
          min={940}
          max={1080}
          step={1}
          disabled={disabled}
          onChange={(value) => {
            onField('qnh_hpa', value);
          }}
        />
        <NumberField
          label="Visibility"
          unit="m"
          value={resolved.visibility_m}
          min={0}
          max={10000}
          step={50}
          disabled={disabled}
          onChange={(value) => {
            onField('visibility_m', value);
          }}
        />
        <NumberField
          label="Temperature"
          unit="°C"
          value={resolved.temperature_c}
          min={-40}
          max={50}
          step={1}
          disabled={disabled}
          onChange={(value) => {
            onField('temperature_c', value);
          }}
        />
        <NumberField
          label="Dewpoint"
          unit="°C"
          value={resolved.dewpoint_c}
          min={-40}
          max={resolved.temperature_c}
          step={1}
          disabled={disabled}
          onChange={(value) => {
            onField('dewpoint_c', Math.min(value, resolved.temperature_c));
          }}
        />
      </div>
    </fieldset>
  );
}
