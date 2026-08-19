/**
 * The bottom bar: the aircraft configuration, what rides along with the position, and the
 * one button that moves the aeroplane.
 *
 * Two things happen here that the rest of the screen depends on.
 *
 * **The staged placement is mirrored onto `positionSlice`.** That slice is the shared
 * server-intent contract: `features/map`'s "send to Position tab" hand-off reads it, and
 * `features/profiles`' Save button is disabled until `staged !== null`. Staging is not a
 * commit — nothing moves until the button is pressed — so the mirror runs whenever the
 * screen resolves to a placement.
 *
 * **Every configuration field defaults to the preview's own value and is only sent when the
 * instructor changes it.** An empty IAS box does not mean 0 kt; it means "whatever the
 * placement resolved", which for a final is the approach-category speed the server worked
 * out. Shipping a hard-coded number here would put an aeroplane below stall speed on a
 * 10 NM final, which is the failure CLAUDE.md's placement-speed note exists to prevent.
 */

import { useEffect, useState } from 'react';
import {
  useApplyPlacementMutation,
  useGetCapabilitiesQuery,
} from '../../api/instructorApi';
import type { AircraftSetup } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import { tabSelected as moduleTabSelected } from '../../store/uiSlice';
import { errorMessage } from './errors';
import { formatAltitudeFt, formatSpeedKt } from './format';
import { commitGate } from './gate';
import {
  configChanged,
  sendToggled,
  situationReset,
  type AircraftConfigState,
} from './positionDesignSlice';
import { placementStaged, setupOverridden } from './positionSlice';
import { overridesOrNull } from './setup';
import { useIls, useSelectedRunway, useStagedPlacement } from './usePositionData';

/** How long the confirmation stays up after a successful commit. MOTION is dialled low. */
const FLASH_MS = 2400;

export function BottomBar() {
  const dispatch = useAppDispatch();
  const config = useAppSelector((state) => state.positionDesign.config);
  const send = useAppSelector((state) => state.positionDesign.send);
  const runway = useSelectedRunway();
  const { ils } = useIls(runway?.ident ?? null);
  const hasIls = ils !== null;

  const { request, preview, merged, setup, isFetching } = useStagedPlacement();
  const { data: capabilities, isError: capabilitiesFailed } = useGetCapabilitiesQuery();
  const gate = commitGate(capabilities, capabilitiesFailed);

  const [applyPlacement, applyState] = useApplyPlacementMutation();
  const [flash, setFlash] = useState<string | null>(null);

  const overrides = setup.overrides;

  // The mirror onto the shared slice. `placementStaged` clears the overrides it finds, so
  // the edits are re-applied in the same effect, after it — never in a separate one whose
  // ordering would depend on where it is declared.
  useEffect(() => {
    if (request === null) {
      return;
    }
    dispatch(placementStaged(request));
    for (const [field, value] of Object.entries(overrides)) {
      dispatch(setupOverridden({ field: field as keyof AircraftSetup, value }));
    }
  }, [dispatch, request, overrides]);

  useEffect(() => {
    if (flash === null) {
      return;
    }
    const handle = window.setTimeout(() => {
      setFlash(null);
    }, FLASH_MS);
    return () => {
      window.clearTimeout(handle);
    };
  }, [flash]);

  function setConfig(field: keyof AircraftConfigState, value: number | boolean | null) {
    dispatch(configChanged({ field, value }));
  }

  function commit() {
    if (request === null) {
      return;
    }
    void applyPlacement({ placement: request, setup: overridesOrNull(overrides) })
      .unwrap()
      .then((result) => {
        setFlash(
          `Placed at ${formatAltitudeFt(result.state.altitude_ft)}, ` +
            `${formatSpeedKt(result.state.ias_kt)}.`,
        );
      })
      .catch(() => {
        // Rendered from applyState.error below; nothing to do here.
      });
  }

  // Shown values fall back to the preview's, so a box is never blank-as-zero.
  const iasValue =
    config.iasKt ?? (merged.ias_kt == null ? '' : Math.round(merged.ias_kt));
  const pitchValue =
    config.pitchDeg ?? (merged.pitch_deg == null ? '' : Math.round(merged.pitch_deg));
  const gearValue = config.gearDown ?? merged.gear_down ?? false;
  const flapsOn = config.flapsPercent !== null;
  const flapsValue =
    config.flapsPercent ??
    (merged.flaps_ratio == null ? 0 : Math.round(merged.flaps_ratio * 100));

  const blocked = !gate.open || request === null;

  return (
    <div className="pos-bottombar">
      <fieldset className="pos-bottombar__group">
        <legend className="pos-bottombar__group-title">
          Aircraft configuration · editable
        </legend>
        <label className="pos-field">
          <span className="pos-field__label">IAS (kt)</span>
          <input
            type="number"
            className="pos-field__input pos-mono"
            value={iasValue}
            onChange={(event) => {
              setConfig(
                'iasKt',
                event.target.value === '' ? null : Number(event.target.value),
              );
            }}
          />
        </label>
        <label className="pos-field">
          <span className="pos-field__label">Pitch (°)</span>
          <input
            type="number"
            className="pos-field__input pos-mono"
            value={pitchValue}
            onChange={(event) => {
              setConfig(
                'pitchDeg',
                event.target.value === '' ? null : Number(event.target.value),
              );
            }}
          />
        </label>
        <label className="pos-checkbox">
          <input
            type="checkbox"
            className="pos-checkbox__input"
            checked={gearValue}
            onChange={(event) => {
              setConfig('gearDown', event.target.checked);
            }}
          />
          <span className="pos-checkbox__box" aria-hidden="true" />
          Gear down
        </label>
        <label className="pos-checkbox">
          <input
            type="checkbox"
            className="pos-checkbox__input"
            checked={flapsOn}
            onChange={(event) => {
              setConfig('flapsPercent', event.target.checked ? flapsValue : null);
            }}
          />
          <span className="pos-checkbox__box" aria-hidden="true" />
          Flaps
        </label>
        <label className="pos-field">
          <span className="pos-field__label">Flaps %</span>
          <input
            type="number"
            className="pos-field__input pos-mono"
            disabled={!flapsOn}
            value={flapsValue}
            onChange={(event) => {
              setConfig('flapsPercent', Number(event.target.value));
            }}
          />
        </label>
        <label className="pos-checkbox">
          <input
            type="checkbox"
            className="pos-checkbox__input"
            checked={config.altitudeOverride}
            onChange={(event) => {
              setConfig('altitudeOverride', event.target.checked);
            }}
          />
          <span className="pos-checkbox__box" aria-hidden="true" />
          Override altitude
        </label>
        <label className="pos-field">
          <span className="pos-field__label">Override altitude (ft)</span>
          <input
            type="number"
            className="pos-field__input pos-mono"
            disabled={!config.altitudeOverride}
            value={config.altitudeOverrideFt}
            onChange={(event) => {
              setConfig('altitudeOverrideFt', Number(event.target.value));
            }}
          />
        </label>
      </fieldset>

      <div className="pos-bottombar__divider" aria-hidden="true" />

      <fieldset className="pos-bottombar__group">
        <legend className="pos-bottombar__group-title">Sent with the position</legend>
        <label className="pos-checkbox">
          <input
            type="checkbox"
            className="pos-checkbox__input"
            checked={send.heading}
            onChange={() => {
              dispatch(sendToggled('heading'));
            }}
          />
          <span className="pos-checkbox__box" aria-hidden="true" />
          Heading
        </label>
        <label
          className={hasIls ? 'pos-checkbox' : 'pos-checkbox pos-checkbox--disabled'}
        >
          <input
            type="checkbox"
            className="pos-checkbox__input"
            checked={send.course}
            disabled={!hasIls}
            onChange={() => {
              dispatch(sendToggled('course'));
            }}
          />
          <span className="pos-checkbox__box" aria-hidden="true" />
          Course
          {!hasIls && <span className="pos-mono pos-bottombar__na"> n/a</span>}
        </label>
        <label
          className={hasIls ? 'pos-checkbox' : 'pos-checkbox pos-checkbox--disabled'}
        >
          <input
            type="checkbox"
            className="pos-checkbox__input"
            checked={send.ilsFrequency}
            disabled={!hasIls}
            onChange={() => {
              dispatch(sendToggled('ilsFrequency'));
            }}
          />
          <span className="pos-checkbox__box" aria-hidden="true" />
          ILS frequency
          {!hasIls && <span className="pos-mono pos-bottombar__na"> n/a</span>}
        </label>
      </fieldset>

      <div className="pos-bottombar__spacer" />

      <div className="pos-bottombar__actions">
        <button
          type="button"
          className="pos-textaction"
          onClick={() => {
            dispatch(moduleTabSelected('map'));
          }}
        >
          Show on map
        </button>
        <div className="pos-bottombar__commit">
          {!gate.open && <p className="pos-bottombar__blocked">{gate.reason}</p>}
          {request === null && gate.open && (
            <p className="pos-bottombar__blocked">
              Nothing to place yet — load an airport and pick a start position.
            </p>
          )}
          {applyState.isError && (
            <p className="pos-bottombar__error">
              {errorMessage(applyState.error, 'The placement could not be applied.')}
            </p>
          )}
          {flash !== null && <p className="pos-bottombar__flash">{flash}</p>}
          <button
            type="button"
            className="pos-bottombar__set"
            disabled={
              blocked || isFetching || applyState.isLoading || preview === undefined
            }
            onClick={commit}
          >
            {applyState.isLoading ? 'Placing…' : 'Set position'}
            <span className="pos-bottombar__set-sub">
              Moves the aircraft now · sim stays paused
            </span>
          </button>
        </div>
        <button
          type="button"
          className="pos-textaction pos-textaction--danger-on-hover"
          onClick={() => {
            dispatch(situationReset());
          }}
        >
          Reset situation
        </button>
      </div>
    </div>
  );
}
