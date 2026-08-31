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
import { buildManualWeatherRequest, buildWeatherRequest, mergeForDisplay } from './resolve';
import {
  useApplyWeatherMutation,
  useGetWeatherManifestQuery,
  useGetWeatherStateQuery,
  usePreviewWeatherQuery,
} from './weatherApi';
import { overrideSet, stagingCleared, weatherSource } from './weatherSlice';
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
  const source = weatherSource({ selectedPresetId, overrides, staged });
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
  // it lands. Manual mode (WS-2) never previews at all — a setup-only preview would just
  // echo the setup back.
  const previewRequest =
    source === 'preset' && preset !== undefined
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

  // Preset mode: the server's resolved preset over the current weather, then the
  // instructor's own overrides over that. Manual mode and the unstaged case share one path —
  // the current weather with the (possibly empty) overrides replacing whatever they touch,
  // computed client-side with no server round-trip. An empty overlay is exactly `current`
  // itself, which is what lets the editors show — and edit — today's weather before anything
  // is staged at all (WS-1: staging only happens once the instructor actually changes a field).
  const resolved: WeatherState | null =
    current === undefined
      ? null
      : source === 'preset'
        ? preview !== undefined
          ? mergeForDisplay(mergeForDisplay(current, preview.setup), overrides)
          : null
        : mergeForDisplay(current, overrides);

  // WS-1's edge case: an override added then deleted can leave `staged=true, overrides={}` —
  // a manual stage with nothing to send, which the server would refuse (422: neither preset
  // nor setup). Disable Apply and say why, rather than let it 422.
  const manualOverridesEmpty = source === 'manual' && Object.keys(overrides).length === 0;

  const commit = () => {
    if (source === 'preset') {
      if (preset === undefined) {
        return;
      }
      void applyWeather(
        buildWeatherRequest(preset.id, overrides, selectedIcao, selectedRunwayIdent),
      )
        .unwrap()
        .then(() => dispatch(stagingCleared()))
        .catch(() => {
          // Rendered from applyState.isError below; nothing to do here.
        });
      return;
    }
    if (source === 'manual' && !manualOverridesEmpty) {
      void applyWeather(buildManualWeatherRequest(overrides))
        .unwrap()
        .then(() => dispatch(stagingCleared()))
        .catch(() => {
          // Rendered from applyState.isError below; nothing to do here.
        });
    }
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

      {source === 'preset' && previewFailed && (
        <p className="panel__error">
          {errorMessage(previewError, 'This weather could not be worked out.')}
        </p>
      )}

      {source === 'preset' && !previewFailed && resolved === null && (
        <p className="panel__empty">Working out the weather…</p>
      )}

      {gate.open && resolved !== null && (
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
      )}

      {source !== null && resolved !== null && (
        <WeatherStagingBar
          {...(preset !== undefined ? { presetLabel: preset.label } : {})}
          resolved={resolved}
          applying={applyState.isLoading || previewFetching}
          disabledReason={
            manualOverridesEmpty ? 'No changes yet — edit a field to apply.' : null
          }
          errorText={
            applyState.isError
              ? errorMessage(applyState.error, 'The weather could not be applied.')
              : null
          }
          onApply={commit}
          onDismiss={() => dispatch(stagingCleared())}
        />
      )}
    </section>
  );
}
