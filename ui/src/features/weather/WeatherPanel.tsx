/**
 * The weather station: current environment, editable atmosphere profile, presets,
 * selected-layer controls and a draft applied only through the staging bar.
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
import { useRef, useState } from 'react';
import { useGetCapabilitiesQuery } from '../../api/instructorApi';
import type { WeatherSetup, WeatherState } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import { AtmosphereProfile, type AtmosphereSelection } from './AtmosphereProfile';
import { StationEditors } from './StationEditors';
import { weatherValidationError } from './validation';
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
import {
  buildManualWeatherRequest,
  buildWeatherRequest,
  mergeForDisplay,
} from './resolve';
import {
  useApplyWeatherMutation,
  useGetWeatherManifestQuery,
  useGetWeatherAirportQuery,
  useGetWeatherStateQuery,
  usePreviewWeatherQuery,
} from './weatherApi';
import { overrideSet, stagingCleared, weatherSource } from './weatherSlice';
import { WeatherStagingBar } from './WeatherStagingBar';
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
  const [selection, setSelection] = useState<AtmosphereSelection | null>(null);
  const [invalidFields, setInvalidFields] = useState(false);
  const [editorRevision, setEditorRevision] = useState(0);
  const applyingRef = useRef(false);
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
  const {
    data: current,
    isError: currentFailed,
    isFetching: refreshing,
    refetch,
  } = useGetWeatherStateQuery(undefined, { refetchOnMountOrArgChange: true });
  const { data: airport } = useGetWeatherAirportQuery(selectedIcao ?? '', {
    skip: selectedIcao === null,
  });
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
    currentData: preview,
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
  const validationError = resolved === null ? null : weatherValidationError(resolved);
  const disabledReason = !gate.open
    ? gate.reason
    : manifest?.supported === false
      ? (manifest.reason ?? 'Weather is not supported.')
      : previewFailed
        ? 'Resolve the preset before applying.'
        : invalidFields
          ? 'Complete or correct the highlighted fields.'
          : (validationError ??
            (manualOverridesEmpty ? 'No changes yet — edit a field to apply.' : null));
  const resetEditors = () => {
    setInvalidFields(false);
    setEditorRevision((revision) => revision + 1);
    setSelection(null);
  };
  const commit = async () => {
    if (
      applyingRef.current ||
      applyState.isLoading ||
      previewFetching ||
      disabledReason !== null ||
      resolved === null ||
      source === null
    )
      return;
    const request =
      source === 'preset' && preset !== undefined
        ? buildWeatherRequest(preset.id, overrides, selectedIcao, selectedRunwayIdent)
        : source === 'manual' && !manualOverridesEmpty
          ? buildManualWeatherRequest(overrides)
          : null;
    if (request === null) return;
    applyingRef.current = true;
    try {
      await applyWeather(request).unwrap();
      dispatch(stagingCleared());
      resetEditors();
    } catch {
      // The mutation refreshes actual weather while retaining this draft.
    } finally {
      applyingRef.current = false;
    }
  };
  const safeSelection: AtmosphereSelection | null =
    selection !== null &&
    resolved !== null &&
    selection.index <
      (selection.kind === 'wind' ? resolved.wind_layers : resolved.cloud_layers).length
      ? selection
      : resolved !== null && resolved.wind_layers.length > 0
        ? { kind: 'wind', index: 0 }
        : resolved !== null && resolved.cloud_layers.length > 0
          ? { kind: 'cloud', index: 0 }
          : null;
  const setField = (field: keyof WeatherSetup, value: unknown) => {
    dispatch(overrideSet({ field, value }));
  };
  return (
    <section className="panel weather-panel" aria-labelledby="weather-heading">
      <div className="weather-station-header">
        <div>
          <h2 id="weather-heading">Weather</h2>
          <p className="weather-panel__blocked">
            {selectedIcao ?? 'No airport selected'}
            {selectedRunwayIdent === null ? '' : ` · Runway ${selectedRunwayIdent}`}
            {airport === undefined
              ? ' · Heights MSL'
              : ` · Field ${Math.round(airport.elevation_ft)} ft MSL`}
            {' · '}
            {staged || invalidFields ? 'Pending changes' : 'Current weather'}
          </p>
        </div>
        <button
          type="button"
          className="weather-group__add"
          disabled={refreshing || applyState.isLoading}
          onClick={() => {
            void refetch();
          }}
        >
          {refreshing ? 'Refreshing…' : 'Refresh weather'}
        </button>
      </div>
      {current !== undefined && <CurrentWeather current={current} />}
      {!gate.open && <p className="weather-panel__blocked">{gate.reason}</p>}
      {gate.open && manifest?.supported === false && (
        <p className="weather-panel__blocked">
          {manifest.reason ?? 'Weather is not supported.'}
        </p>
      )}
      {applyState.isSuccess && !staged && (
        <p className="weather-panel__flash" role="status">
          Weather applied.
        </p>
      )}
      {currentFailed && (
        <p className="panel__error" role="alert">
          The current weather could not be refreshed. Pending changes are preserved.
        </p>
      )}
      <div className="weather-station-grid">
        <div className="weather-station-profile">
          {resolved !== null && (
            <AtmosphereProfile
              state={resolved}
              fieldElevationFt={airport?.elevation_ft ?? null}
              selection={safeSelection}
              readOnly={
                !gate.open ||
                manifest?.supported === false ||
                applyState.isLoading ||
                previewFetching ||
                invalidFields
              }
              onSelect={setSelection}
              onWindLayersChange={(layers) => setField('wind_layers', layers)}
              onCloudLayersChange={(layers) => setField('cloud_layers', layers)}
            />
          )}
        </div>
        <div className="weather-station-controls">
          <PresetGrid
            presets={manifest?.presets ?? []}
            disabled={
              !gate.open ||
              manifest?.supported === false ||
              applyState.isLoading ||
              invalidFields
            }
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
          {resolved !== null && (
            <StationEditors
              key={`${selectedPresetId ?? 'manual'}:${selectedIcao ?? ''}:${editorRevision}`}
              resolved={resolved}
              selection={safeSelection}
              disabled={
                !gate.open ||
                manifest?.supported === false ||
                applyState.isLoading ||
                previewFetching
              }
              onSelect={setSelection}
              onField={setField}
              onInvalidChange={setInvalidFields}
            />
          )}
        </div>
      </div>
      {(source !== null || invalidFields) && resolved !== null && (
        <WeatherStagingBar
          {...(preset !== undefined ? { presetLabel: preset.label } : {})}
          resolved={resolved}
          applying={applyState.isLoading || previewFetching}
          disabledReason={disabledReason}
          errorText={
            applyState.isError
              ? errorMessage(applyState.error, 'The weather could not be applied.')
              : null
          }
          onApply={commit}
          onDismiss={() => {
            dispatch(stagingCleared());
            applyState.reset();
            resetEditors();
          }}
        />
      )}
    </section>
  );
}
