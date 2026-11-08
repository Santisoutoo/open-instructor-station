/**
 * The scalar half of the staged weather: QNH, visibility, temperature, dewpoint,
 * precipitation and runway contamination.
 *
 * Numeric inputs retain unfinished entries; the container validates the complete
 * resolved instruction, including the temperature/dewpoint relationship.
 */

import { formatContamination } from './format';
import { NumberField } from './NumberField';
import type { RunwayContamination, WeatherSetup, WeatherState } from '../../api/models';

const CONTAMINATIONS: readonly RunwayContamination[] = [
  'dry',
  'wet',
  'puddles',
  'snow',
  'ice',
];

interface AtmosphereFormProps {
  /** The resolved staged weather — current weather with the setup's touched fields replacing it. */
  resolved: WeatherState;
  disabled: boolean;
  onField: (field: keyof WeatherSetup, value: number) => void;
  onContamination: (value: RunwayContamination) => void;
}

export function AtmosphereForm({
  resolved,
  disabled,
  onField,
  onContamination,
}: AtmosphereFormProps) {
  return (
    <fieldset className="weather-group">
      <legend className="weather-group__title">Atmosphere</legend>
      <div className="weather-row">
        <NumberField
          label="QNH"
          unit="hPa"
          value={resolved.qnh_hpa}
          min={900}
          max={1100}
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
          max={Infinity}
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
          min={-60}
          max={60}
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
          min={-60}
          max={Math.min(60, resolved.temperature_c)}
          rangeError="Dewpoint must not exceed temperature."
          step={1}
          disabled={disabled}
          onChange={(value) => {
            onField('dewpoint_c', value);
          }}
        />
        <NumberField
          label="Precipitation"
          unit="%"
          value={resolved.precipitation_ratio * 100}
          min={0}
          max={100}
          step={5}
          disabled={disabled}
          onChange={(value) => {
            onField('precipitation_ratio', value / 100);
          }}
        />
        <label className="weather-field">
          <span className="weather-field__label">Surface</span>
          <select
            className="weather-field__input weather-field__input--select"
            value={resolved.runway_contamination}
            disabled={disabled}
            onChange={(event) => {
              onContamination(event.target.value as RunwayContamination);
            }}
          >
            {CONTAMINATIONS.map((contamination) => (
              <option key={contamination} value={contamination}>
                {formatContamination(contamination)}
              </option>
            ))}
          </select>
        </label>
      </div>
    </fieldset>
  );
}
