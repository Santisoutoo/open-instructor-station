/**
 * The Save form: name/description/author, an "include current weather" toggle, and an
 * inline failure-list builder reusing the already-generated Failures catalogue query and
 * the shared `FailureId`/`FailureTrigger` types (design §7.3) — no new catalogue, no new
 * trigger vocabulary. Reads (D11) `positionSlice`'s and `weatherSlice`'s already-public
 * staged state through `./selectors`, never dispatches into either.
 *
 * Disabled with a stated reason when nothing is staged in Position (D11's "nothing to
 * save" fail-closed) — the profile *is* the staged placement plus whatever else the
 * instructor opts to attach, so there is nothing to compose without one.
 */

import { useState } from 'react';
import type { FailureId, FailureTrigger, FailureTriggerType, TrainingProfileCreate } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import { useGetFailuresCatalogueQuery } from '../failures/failuresApi';
import { defaultTrigger, TRIGGER_TYPES } from '../failures/triggers';
import { buildWeatherRequest } from '../weather/resolve';
import { useCreateProfileMutation } from './profilesApi';
import type { ProfileFailureDraft } from './profilesSlice';
import {
  saveDraftAuthorChanged,
  saveDraftDescriptionChanged,
  saveDraftFailureAdded,
  saveDraftFailureRemoved,
  saveDraftIncludeWeatherToggled,
  saveDraftNameChanged,
  saveDraftReset,
} from './profilesSlice';
import {
  selectPositionSetupOverrides,
  selectSelectedIcao,
  selectSelectedRunwayIdent,
  selectStagedPlacement,
  selectStagedWeatherPresetId,
  selectWeatherIsStaged,
  selectWeatherOverrides,
} from './selectors';

const WHEN_LABELS: Readonly<Record<'immediate' | FailureTriggerType, string>> = {
  immediate: 'Immediately',
  altitude_above: 'At or above altitude',
  altitude_below: 'At or below altitude',
  speed_above: 'At or above IAS',
  speed_below: 'At or below IAS',
  delay: 'After delay',
};

function failureSummary(draft: ProfileFailureDraft): string {
  const engine = draft.engineIndex === null ? '' : ` (engine ${draft.engineIndex})`;
  if (draft.trigger === null) {
    return `${draft.failureId}${engine} — immediately`;
  }
  const trigger = draft.trigger;
  if (trigger.type === 'altitude_above' || trigger.type === 'altitude_below') {
    return `${draft.failureId}${engine} — ${WHEN_LABELS[trigger.type]} ${trigger.altitude_ft} ft`;
  }
  if (trigger.type === 'speed_above' || trigger.type === 'speed_below') {
    return `${draft.failureId}${engine} — ${WHEN_LABELS[trigger.type]} ${trigger.ias_kt} kt`;
  }
  return `${draft.failureId}${engine} — after ${trigger.delay_s} s`;
}

function FailureBuilder() {
  const dispatch = useAppDispatch();
  const { data: catalogue } = useGetFailuresCatalogueQuery();
  const supported = (catalogue?.failures ?? []).filter((entry) => entry.supported);

  const [failureId, setFailureId] = useState<FailureId | ''>('');
  // Never blank -- an indexed failure's engine_index is required (FailureRef.engine_index:
  // "Required iff the entry is indexed"), so the field always holds a valid 1-8 value rather
  // than risking a silent `null` that only surfaces as a generic 422 at save time. Mirrors
  // FailureRow.tsx's own `useState(1)` for the same reason.
  const [engineIndex, setEngineIndex] = useState<number>(1);
  const [when, setWhen] = useState<'immediate' | FailureTriggerType>('immediate');
  const [threshold, setThreshold] = useState<number | ''>('');

  const entry = supported.find((candidate) => candidate.failure_id === failureId);

  const add = () => {
    if (failureId === '') {
      return;
    }
    let trigger: FailureTrigger | null = null;
    if (when !== 'immediate') {
      const base = defaultTrigger(when);
      trigger =
        threshold === ''
          ? base
          : (() => {
              if (base.type === 'altitude_above' || base.type === 'altitude_below') {
                return { ...base, altitude_ft: threshold };
              }
              if (base.type === 'speed_above' || base.type === 'speed_below') {
                return { ...base, ias_kt: threshold };
              }
              return { ...base, delay_s: threshold };
            })();
    }
    dispatch(
      saveDraftFailureAdded({
        failureId,
        engineIndex: entry?.takes_engine_index === true ? engineIndex : null,
        trigger,
      }),
    );
    setFailureId('');
    setEngineIndex(1);
    setWhen('immediate');
    setThreshold('');
  };

  const failures = useAppSelector((state) => state.profiles.saveDraft.failures);

  return (
    <fieldset className="profiles-form__failures">
      <legend>Failures</legend>
      {failures.length > 0 && (
        <ul className="profiles-form__failure-list">
          {failures.map((draft, index) => (
            <li key={`${draft.failureId}-${index}`} className="profiles-form__failure-item">
              <span>{failureSummary(draft)}</span>
              <button
                type="button"
                onClick={() => {
                  dispatch(saveDraftFailureRemoved(index));
                }}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="profiles-form__failure-builder">
        <select
          aria-label="Failure"
          value={failureId}
          onChange={(event) => {
            setFailureId(event.target.value as FailureId | '');
          }}
        >
          <option value="">Add a failure…</option>
          {supported.map((candidate) => (
            <option key={candidate.failure_id} value={candidate.failure_id}>
              {candidate.label}
            </option>
          ))}
        </select>

        {entry?.takes_engine_index === true && (
          <input
            aria-label="Engine index"
            type="number"
            min={1}
            max={8}
            value={engineIndex}
            onChange={(event) => {
              // An invalid or out-of-range edit is simply not applied, rather than being
              // allowed to clear the field -- engineIndex must always be a valid 1-8 value.
              const value = Number(event.target.value);
              if (Number.isFinite(value) && value >= 1 && value <= 8) {
                setEngineIndex(value);
              }
            }}
          />
        )}

        <select
          aria-label="When"
          value={when}
          onChange={(event) => {
            setWhen(event.target.value as 'immediate' | FailureTriggerType);
            setThreshold('');
          }}
        >
          {(['immediate', ...TRIGGER_TYPES] as const).map((option) => (
            <option key={option} value={option}>
              {WHEN_LABELS[option]}
            </option>
          ))}
        </select>

        {when !== 'immediate' && (
          <input
            aria-label="Trigger threshold"
            type="number"
            placeholder="Threshold"
            value={threshold}
            onChange={(event) => {
              const value = Number(event.target.value);
              setThreshold(event.target.value === '' || !Number.isFinite(value) ? '' : value);
            }}
          />
        )}

        <button type="button" disabled={failureId === ''} onClick={add}>
          Add
        </button>
      </div>
    </fieldset>
  );
}

export function SaveProfileForm() {
  const dispatch = useAppDispatch();
  const draft = useAppSelector((state) => state.profiles.saveDraft);
  const stagedPlacement = useAppSelector(selectStagedPlacement);
  const setupOverrides = useAppSelector(selectPositionSetupOverrides);
  const weatherStaged = useAppSelector(selectWeatherIsStaged);
  const presetId = useAppSelector(selectStagedWeatherPresetId);
  const weatherOverrides = useAppSelector(selectWeatherOverrides);
  const selectedIcao = useAppSelector(selectSelectedIcao);
  const selectedRunwayIdent = useAppSelector(selectSelectedRunwayIdent);

  const [createProfile, createState] = useCreateProfileMutation();

  const canSave = stagedPlacement !== null && draft.name.trim() !== '';
  const disabledReason =
    stagedPlacement === null
      ? 'Stage a placement in Position first — a profile always carries a position.'
      : draft.name.trim() === ''
        ? 'Give the profile a name.'
        : null;

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSave || stagedPlacement === null) {
      return;
    }
    const hasOverrides = Object.keys(setupOverrides).length > 0;
    const hasFailures = draft.failures.length > 0;
    const includeWeather = draft.includeWeather && weatherStaged && presetId !== null;

    const body: TrainingProfileCreate = {
      name: draft.name,
      description: draft.description,
      author: draft.author === '' ? null : draft.author,
      scenario: {
        name: draft.name,
        description: draft.description || draft.name,
        tags: [],
        position: stagedPlacement,
        aircraft_state: hasOverrides ? setupOverrides : null,
        weather:
          includeWeather && presetId !== null
            ? buildWeatherRequest(presetId, weatherOverrides, selectedIcao, selectedRunwayIdent)
            : null,
        failures: hasFailures
          ? {
              immediate: draft.failures
                .filter((entry) => entry.trigger === null)
                .map((entry) => ({ failure_id: entry.failureId, engine_index: entry.engineIndex })),
              armed: draft.failures
                .filter((entry) => entry.trigger !== null)
                .map((entry) => ({
                  failure_id: entry.failureId,
                  engine_index: entry.engineIndex,
                  trigger: entry.trigger as FailureTrigger,
                })),
            }
          : null,
        traffic: null,
      },
    };

    void createProfile(body)
      .unwrap()
      .then(() => {
        dispatch(saveDraftReset());
      })
      .catch(() => {
        // Rendered from createState.isError below; nothing to do here.
      });
  };

  return (
    <form className="profiles-form" onSubmit={handleSubmit}>
      <div className="profiles-form__fields">
        <label>
          Name
          <input
            type="text"
            value={draft.name}
            onChange={(event) => {
              dispatch(saveDraftNameChanged(event.target.value));
            }}
          />
        </label>
        <label>
          Description
          <textarea
            value={draft.description}
            onChange={(event) => {
              dispatch(saveDraftDescriptionChanged(event.target.value));
            }}
          />
        </label>
        <label>
          Author
          <input
            type="text"
            value={draft.author}
            onChange={(event) => {
              dispatch(saveDraftAuthorChanged(event.target.value));
            }}
          />
        </label>
        <label className="profiles-form__checkbox">
          <input
            type="checkbox"
            checked={draft.includeWeather}
            disabled={!weatherStaged}
            onChange={() => {
              dispatch(saveDraftIncludeWeatherToggled());
            }}
          />
          Include current weather
        </label>
      </div>

      <FailureBuilder />

      {disabledReason !== null && <p className="profiles-form__reason">{disabledReason}</p>}
      {createState.isError && <p className="panel__error">The profile could not be saved.</p>}

      <button type="submit" disabled={!canSave || createState.isLoading}>
        Save profile
      </button>
    </form>
  );
}
