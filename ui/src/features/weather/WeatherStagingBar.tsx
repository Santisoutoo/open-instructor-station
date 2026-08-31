/**
 * The staging bar — the reason the Weather panel is safe to use during a lesson.
 *
 * Staging a preset changes nothing in the simulator. This bar shows the *resolved* values —
 * the current weather with the staged preset + the instructor's overrides replacing whatever
 * they actually touch — and **one** solid-accent button commits them. Errors render here,
 * inline; never a modal over a running lesson.
 */

import {
  formatCloudSummary,
  formatContamination,
  formatPrecipitation,
  formatQnh,
  formatTempDew,
  formatVisibility,
  formatWind,
} from './format';
import type { WeatherState } from '../../api/models';

interface WeatherStagingBarProps {
  /** Absent in manual mode — nothing was staged from a preset. */
  presetLabel?: string;
  /** The resolved staged weather — exactly what Apply will commit. */
  resolved: WeatherState;
  applying: boolean;
  /** Non-null disables Apply and is shown inline as the reason why. `null` otherwise. */
  disabledReason: string | null;
  /** Rendered inline when the apply mutation failed. `null` otherwise. */
  errorText: string | null;
  onApply: () => void;
  onDismiss: () => void;
}

export function WeatherStagingBar({
  presetLabel,
  resolved,
  applying,
  disabledReason,
  errorText,
  onApply,
  onDismiss,
}: WeatherStagingBarProps) {
  const surface = resolved.wind_layers[0];
  const values: { label: string; value: string }[] = [
    { label: 'wind', value: surface === undefined ? 'calm' : formatWind(surface) },
    { label: 'vis', value: formatVisibility(resolved.visibility_m) },
    { label: 'QNH', value: formatQnh(resolved.qnh_hpa) },
    {
      label: 'temp / dew',
      value: formatTempDew(resolved.temperature_c, resolved.dewpoint_c),
    },
    { label: 'cloud', value: formatCloudSummary(resolved) },
    { label: 'precip', value: formatPrecipitation(resolved.precipitation_ratio) },
    { label: 'surface', value: formatContamination(resolved.runway_contamination) },
  ];
  const label = presetLabel === undefined ? 'Manual weather' : `Staged: ${presetLabel}`;

  return (
    <section className="weather-staging" aria-label="Staged weather">
      <p className="weather-staging__label">{label}</p>
      <dl className="weather-staging__values">
        {values.map((entry) => (
          <div className="weather-staging__item" key={entry.label}>
            <dt className="weather-staging__key">{entry.label}</dt>
            <dd className="weather-staging__value">{entry.value}</dd>
          </div>
        ))}
      </dl>
      {errorText !== null && <p className="panel__error">{errorText}</p>}
      {disabledReason !== null && <p className="panel__empty">{disabledReason}</p>}
      <div className="weather-staging__actions">
        <button
          type="button"
          className="weather-staging__dismiss"
          disabled={applying}
          onClick={onDismiss}
        >
          Clear
        </button>
        <button
          type="button"
          className="weather-staging__apply"
          disabled={applying || disabledReason !== null}
          onClick={onApply}
        >
          {applying ? 'Applying…' : 'Apply weather'}
        </button>
      </div>
    </section>
  );
}
