/**
 * The Weather Manager panel: the current environment, the seven-preset grid, and —
 * once a preset is staged — the layer editors and the staging bar.
 *
 * Staging is client state (the slice); the current weather is server state (RTK
 * Query). The panel reads the Position panel's airport and runway to resolve
 * relative presets, and only reads: it never dispatches into position.
 */

import { useAppDispatch, useAppSelector } from '../../store';
import { AtmosphereForm } from './AtmosphereForm';
import { CloudLayerEditor } from './CloudLayerEditor';
import {
  formatCloudSummary,
  formatQnh,
  formatTempDew,
  formatVisibility,
  formatWind,
} from './format';
import { weatherGate } from './gate';
import { presetById, resolveWeather } from './mock';
import { PresetGrid } from './PresetGrid';
import type { RunwayRef, WeatherState } from './types.mock';
import { useApplyWeatherMutation, useGetWeatherStateQuery } from './weatherApi';
import { overrideSet, stagingCleared } from './weatherSlice';
import { WeatherStagingBar } from './WeatherStagingBar';
import { WindLayerEditor } from './WindLayerEditor';
import './weather.css';

function CurrentWeather({ current }: { current: WeatherState }) {
  const surface = current.wind_layers[0];
  const readouts = [
    { label: 'Wind', value: surface === undefined ? 'calm' : formatWind(surface) },
    { label: 'Visibility', value: formatVisibility(current.visibility_m) },
    { label: 'QNH', value: formatQnh(current.qnh_hpa) },
    {
      label: 'Temp / dew',
      value: formatTempDew(current.temperature_c, current.dewpoint_c),
    },
    { label: 'Cloud', value: formatCloudSummary(current) },
    { label: 'Precipitation', value: current.precipitation },
  ];
  return (
    <dl className="readouts">
      {readouts.map((readout) => (
        <div className="readout" key={readout.label}>
          <dt className="readout__label">{readout.label}</dt>
          <dd className="readout__value readout__value--weather">{readout.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function WeatherPanel() {
  const dispatch = useAppDispatch();
  const { selectedPresetId, overrides, staged } = useAppSelector(
    (state) => state.weather,
  );
  // Read-only prefill from the Position panel — never dispatched into.
  const selectedIcao = useAppSelector((state) => state.position.selectedIcao);
  const selectedRunwayIdent = useAppSelector(
    (state) => state.position.selectedRunwayIdent,
  );

  const { data: current, isError } = useGetWeatherStateQuery();
  const gate = weatherGate(current, isError);
  const [applyWeather, applyState] = useApplyWeatherMutation();

  const runway: RunwayRef | null =
    selectedIcao !== null && selectedRunwayIdent !== null
      ? { icao: selectedIcao, ident: selectedRunwayIdent }
      : null;

  const preset = selectedPresetId === null ? undefined : presetById(selectedPresetId);
  const resolved =
    staged && preset !== undefined ? resolveWeather(preset, overrides, runway) : null;

  const commit = () => {
    if (preset === undefined) {
      return;
    }
    void applyWeather({ preset_id: preset.id, overrides, runway })
      .unwrap()
      .then(() => dispatch(stagingCleared()))
      .catch(() => {
        // Rendered from applyState.isError below; nothing to do here.
      });
  };

  return (
    <section className="panel weather-panel" aria-labelledby="weather-heading">
      <h2 id="weather-heading">Weather</h2>

      {current !== undefined && <CurrentWeather current={current} />}
      {!gate.open && <p className="weather-panel__blocked">{gate.reason}</p>}
      {applyState.isSuccess && !staged && (
        <p className="weather-panel__flash" role="status">
          Weather applied.
        </p>
      )}

      <PresetGrid
        disabled={!gate.open}
        selectedIcao={selectedIcao}
        selectedRunwayIdent={selectedRunwayIdent}
        onCommit={commit}
      />

      {resolved !== null && preset !== undefined && (
        <>
          <div className="weather-editors">
            <WindLayerEditor
              layers={resolved.wind_layers}
              disabled={applyState.isLoading}
              onChange={(layers) => {
                dispatch(overrideSet({ field: 'wind_layers', value: layers }));
              }}
            />
            <CloudLayerEditor
              layers={resolved.cloud_layers}
              disabled={applyState.isLoading}
              onChange={(layers) => {
                dispatch(overrideSet({ field: 'cloud_layers', value: layers }));
              }}
            />
            <AtmosphereForm
              resolved={resolved}
              disabled={applyState.isLoading}
              onField={(field, value) => {
                dispatch(overrideSet({ field, value }));
              }}
            />
          </div>
          <WeatherStagingBar
            presetLabel={preset.label}
            resolved={resolved}
            applying={applyState.isLoading}
            errorText={applyState.isError ? 'The weather could not be applied.' : null}
            onApply={commit}
            onDismiss={() => dispatch(stagingCleared())}
          />
        </>
      )}
    </section>
  );
}
