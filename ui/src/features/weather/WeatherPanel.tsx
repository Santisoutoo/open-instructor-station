/**
 * The Weather Manager panel: the current environment, the preset grid, and — once a preset
 * is staged — the layer editors and the staging bar.
 *
 * Staging is client state (the slice): which preset, and the instructor's edits on top of
 * it. The current weather and the resolved *preset* are both **server state** — the former
 * from `GET /api/weather`, the latter from `POST /api/weather/preview` (weather-manager.md
 * D7: a client can never hand the server a pre-resolved preset and call it staged, so even
 * staging asks the server what a bare preset resolves to against the selected runway). The
 * instructor's own edits are then merged on top client-side, exactly like
 * `features/position/StagingBar.tsx` merges its `setupOverrides` — only the apply mutation
 * sends them onward. The panel reads the Position panel's airport and runway to resolve
 * relative presets, and only reads: it never dispatches into position.
 */

import { useGetCapabilitiesQuery } from '../../api/instructorApi';
import type { RunwayContamination, WeatherSetup, WeatherState } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import { AtmosphereForm } from './AtmosphereForm';
import { CloudLayerEditor } from './CloudLayerEditor';
import { errorMessage } from './errors';
import {
  formatCloudSummary,
  formatContamination,
  formatPrecipitation,
  formatQnh,
  formatTempDew,
  formatVisibility,
  formatWind,
} from './format';
import { weatherGate } from './gate';
import { PresetGrid } from './PresetGrid';
import { buildWeatherRequest, mergeForDisplay } from './resolve';
import {
  useApplyWeatherMutation,
  useGetWeatherManifestQuery,
  useGetWeatherStateQuery,
  usePreviewWeatherQuery,
} from './weatherApi';
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
    { label: 'Precipitation', value: formatPrecipitation(current.precipitation_ratio) },
    { label: 'Surface', value: formatContamination(current.runway_contamination) },
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

  const { data: capabilities, isError: capabilitiesFailed } = useGetCapabilitiesQuery();
  const { data: current, isError: currentFailed } = useGetWeatherStateQuery();
  const { data: manifest } = useGetWeatherManifestQuery();
  const gate = weatherGate(capabilities, capabilitiesFailed, current, currentFailed);

  const preset =
    selectedPresetId === null
      ? undefined
      : manifest?.presets.find((candidate) => candidate.id === selectedPresetId);

  // Depends only on the staged preset and the runway context — never on `overrides`.
  // Mirrors `features/position/StagingBar.tsx`: the instructor's own edits are merged
  // client-side (below) rather than round-tripped through the server on every keystroke,
  // which would also reset each edit to whatever the next preview response says the moment
  // it lands.
  const previewRequest =
    staged && preset !== undefined
      ? buildWeatherRequest(preset.id, {}, selectedIcao, selectedRunwayIdent)
      : null;
  const {
    data: preview,
    isFetching: previewFetching,
    isError: previewFailed,
    error: previewError,
  } = usePreviewWeatherQuery(previewRequest ?? ({} as never), {
    skip: previewRequest === null,
  });

  const [applyWeather, applyState] = useApplyWeatherMutation();

  // Two-stage merge: the server's resolved preset over the current weather, then the
  // instructor's own overrides over that — the same shape `mergeForDisplay` already gives
  // for a `WeatherSetup` overlay, applied twice.
  const resolved: WeatherState | null =
    preview !== undefined && current !== undefined
      ? mergeForDisplay(mergeForDisplay(current, preview.setup), overrides)
      : null;

  const commit = () => {
    if (preset === undefined) {
      return;
    }
    void applyWeather(buildWeatherRequest(preset.id, overrides, selectedIcao, selectedRunwayIdent))
      .unwrap()
      .then(() => dispatch(stagingCleared()))
      .catch(() => {
        // Rendered from applyState.isError below; nothing to do here.
      });
  };

  const setField = (field: keyof WeatherSetup, value: unknown) => {
    dispatch(overrideSet({ field, value }));
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
        presets={manifest?.presets ?? []}
        disabled={!gate.open}
        selectedIcao={selectedIcao}
        selectedRunwayIdent={selectedRunwayIdent}
        onCommit={commit}
      />

      {staged && preset !== undefined && previewFailed && (
        <p className="panel__error">
          {errorMessage(previewError, 'This weather could not be worked out.')}
        </p>
      )}

      {staged && preset !== undefined && !previewFailed && resolved === null && (
        <p className="panel__empty">Working out the weather…</p>
      )}

      {resolved !== null && preset !== undefined && (
        <>
          <div className="weather-editors">
            <WindLayerEditor
              layers={resolved.wind_layers}
              disabled={applyState.isLoading}
              onChange={(layers) => {
                setField('wind_layers', layers);
              }}
            />
            <CloudLayerEditor
              layers={resolved.cloud_layers}
              disabled={applyState.isLoading}
              onChange={(layers) => {
                setField('cloud_layers', layers);
              }}
            />
            <AtmosphereForm
              resolved={resolved}
              disabled={applyState.isLoading}
              onField={(field, value) => {
                setField(field, value);
              }}
              onContamination={(value: RunwayContamination) => {
                setField('runway_contamination', value);
              }}
            />
          </div>
          <WeatherStagingBar
            presetLabel={preset.label}
            resolved={resolved}
            applying={applyState.isLoading || previewFetching}
            errorText={
              applyState.isError
                ? errorMessage(applyState.error, 'The weather could not be applied.')
                : null
            }
            onApply={commit}
            onDismiss={() => dispatch(stagingCleared())}
          />
        </>
      )}
    </section>
  );
}
