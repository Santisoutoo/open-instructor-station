/**
 * The bottom bar: the aircraft configuration, what rides along with the position, and the
 * one button that moves the aeroplane.
 *
 * Two things happen here that the rest of the screen depends on.
 *
 * **The staged placement is mirrored onto `positionSlice`.** That slice is the shared
 * server-intent contract: `features/profiles`' Save button is disabled until
 * `staged !== null`. Staging is not a commit — nothing moves until the button is pressed —
 * so the mirror runs whenever the screen resolves to a placement, and **clears the slice
 * when it resolves to nothing**. Leaving the last placement behind is how Profiles ends up
 * offering to save a 10 NM final on a screen that is showing an unpicked procedure.
 *
 * The mirror cannot clobber the Map's hand-off, because the hand-off is *adopted* into the
 * Custom location tab before this ever runs (`coordinateHandoffReceived`): what the screen
 * resolves to is the handed-over coordinate itself.
 *
 * **Every configuration field defaults to the preview's own value and is only sent when the
 * instructor changes it.** An empty IAS box does not mean 0 kt; it means "whatever the
 * placement resolved", which for a final is the approach-category speed the server worked
 * out. Shipping a hard-coded number here would put an aeroplane below stall speed on a
 * 10 NM final, which is the failure CLAUDE.md's placement-speed note exists to prevent.
 */

import { useEffect, useRef, useState } from 'react';
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
  startAtToggled,
  type AircraftConfigState,
} from './positionDesignSlice';
import { placementStaged, setupOverridden, staleCleared } from './positionSlice';
import { overridesOrNull } from './setup';
import { unflyableReason } from './speed';
import { StartAtPopover } from './StartAtPopover';
import { startAtLabelOf, startAtPopoverId } from './startAt';
import {
  useGroundElevationFt,
  useIls,
  useSelectedRunway,
  useStagedPlacement,
} from './usePositionData';

/** How long the confirmation stays up after a successful commit. MOTION is dialled low. */
const FLASH_MS = 2400;

/**
 * What ticking "Flaps" means when the placement resolved none.
 *
 * The tick has to name a setting — a merge cannot say "some flaps" — and this is the one
 * number on this screen the instructor's own act invents rather than the server resolving
 * it. The % box beside the checkbox is where it gets corrected, and the rail prints the
 * result before anything is applied.
 */
const FLAPS_ON_DEFAULT_PERCENT = 25;

export function BottomBar() {
  const dispatch = useAppDispatch();
  const config = useAppSelector((state) => state.positionDesign.config);
  const send = useAppSelector((state) => state.positionDesign.send);
  const selectedRunway = useAppSelector((state) => state.positionDesign.selectedRunway);
  const selectedStand = useAppSelector((state) => state.positionDesign.selectedStand);
  // The second entry point to the Start-at picker (issue #166): an instructor setting flaps
  // and gear down here should not have to travel back to the header to change the stand.
  const startAtOpen = useAppSelector(
    (state) =>
      state.positionDesign.startAtOpen &&
      state.positionDesign.startAtAnchor === 'bottombar',
  );
  const startAtTriggerRef = useRef<HTMLButtonElement>(null);
  const runway = useSelectedRunway();
  // Tri-state on purpose: `null` while the lookup is in flight. Collapsing it to a boolean
  // is what made the bar tell an instructor an ILS runway had none for a frame.
  const { hasIls } = useIls(runway?.ident ?? null);
  const ilsKnown = hasIls === true;

  const { request, preview, merged, setup, isFetching } = useStagedPlacement();
  const { data: capabilities, isError: capabilitiesFailed } = useGetCapabilitiesQuery();
  const gate = commitGate(capabilities, capabilitiesFailed);
  const groundElevationFt = useGroundElevationFt();

  const [applyPlacement, applyState] = useApplyPlacementMutation();
  const [flash, setFlash] = useState<string | null>(null);

  // The Flaps % box's own characters, decoupled from `flapsValue` below while the
  // instructor is mid-edit. `flapsValue` re-derives to the resolved default the instant
  // the field is empty (that's what lets the checkbox and preview panel stay correct), so
  // binding the input to it directly snapped a cleared box straight back to "50" before a
  // second backspace could land — the instructor could delete only the last digit, never
  // both. Left alone while focused, this mirrors the resolved default again once the field
  // blurs empty, or the moment it stops being focused for any other reason.
  const [flapsFocused, setFlapsFocused] = useState(false);
  const [flapsText, setFlapsText] = useState('');
  const [flapsSyncedFrom, setFlapsSyncedFrom] = useState<number | null>(null);

  // "Override altitude (ft)" is a plain `number` in Redux, unlike IAS/Pitch's `number |
  // null` — there is no "leave it alone" meaning to fall back on, since the override is
  // already gated by the `altitudeOverride` switch. A local draft lets the box go empty
  // mid-edit without a phantom 0 ever landing in Redux (and bouncing straight back).
  // Resynced during render — not in an effect — the same way `SliderControl` follows a
  // value that moved out from under it.
  const [altitudeDraft, setAltitudeDraft] = useState<string | null>(null);
  const [altitudeSyncedFrom, setAltitudeSyncedFrom] = useState(config.altitudeOverrideFt);
  if (config.altitudeOverrideFt !== altitudeSyncedFrom) {
    setAltitudeSyncedFrom(config.altitudeOverrideFt);
    setAltitudeDraft(null);
  }
  const altitudeOverrideFtShown = altitudeDraft ?? String(config.altitudeOverrideFt);

  const overrides = setup.overrides;

  // The mirror onto the shared slice. `placementStaged` clears the overrides it finds, so
  // the edits are re-applied in the same effect, after it — never in a separate one whose
  // ordering would depend on where it is declared.
  useEffect(() => {
    if (request === null) {
      dispatch(staleCleared());
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
  // What will actually be applied, the same way the Gear row reads — not "did the
  // instructor override flaps", which rendered the box unchecked while the rail beside it
  // said "Flaps 50 %".
  const flapsValue =
    config.flapsPercent ??
    (merged.flaps_ratio == null ? 0 : Math.round(merged.flaps_ratio * 100));
  const flapsOn = flapsValue > 0;

  // Follows the resolved value the same way SliderControl follows its own external
  // world — adjusted during render, not in an effect, so the sync is visible on the
  // very render it happens rather than one frame later. Blocked while focused so it
  // cannot fight a keystroke; `onBlur` below covers the one case this can't (the
  // instructor leaves the box empty and the resolved value hasn't itself changed).
  if (!flapsFocused && flapsValue !== flapsSyncedFrom) {
    setFlapsSyncedFrom(flapsValue);
    setFlapsText(String(flapsValue));
  }

  const speedReason = unflyableReason({
    altitudeFt: merged.altitude_ft ?? preview?.placement.position.altitude_ft ?? null,
    groundElevationFt,
    iasKt: merged.ias_kt ?? preview?.placement.ias_kt ?? null,
  });

  const blocked = !gate.open || request === null || speedReason !== null;

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
              // Unticking is a real instruction — flaps up — since the server merges and
              // cannot unset. Ticking with nothing resolved has to name a setting.
              setConfig(
                'flapsPercent',
                event.target.checked
                  ? flapsValue > 0
                    ? flapsValue
                    : FLAPS_ON_DEFAULT_PERCENT
                  : 0,
              );
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
            value={flapsText}
            onFocus={() => {
              setFlapsFocused(true);
            }}
            onBlur={() => {
              setFlapsFocused(false);
              // The render-time sync above only fires when `flapsValue` itself changes,
              // which does not catch "left empty, resolved value unchanged" — blurring on
              // an empty box must still restore it.
              setFlapsSyncedFrom(flapsValue);
              setFlapsText(String(flapsValue));
            }}
            onChange={(event) => {
              setFlapsText(event.target.value);
              setConfig(
                'flapsPercent',
                event.target.value === '' ? null : Number(event.target.value),
              );
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
            value={altitudeOverrideFtShown}
            onChange={(event) => {
              const raw = event.target.value;
              setAltitudeDraft(raw);
              if (raw !== '' && Number.isFinite(Number(raw))) {
                setConfig('altitudeOverrideFt', Number(raw));
              }
            }}
          />
        </label>
      </fieldset>

      <div className="pos-bottombar__divider" aria-hidden="true" />

      <fieldset className="pos-bottombar__group">
        <legend className="pos-bottombar__group-title">Sent with the position</legend>
        <label
          className={ilsKnown ? 'pos-checkbox' : 'pos-checkbox pos-checkbox--disabled'}
        >
          <input
            type="checkbox"
            className="pos-checkbox__input"
            checked={send.course}
            disabled={!ilsKnown}
            onChange={() => {
              dispatch(sendToggled('course'));
            }}
          />
          <span className="pos-checkbox__box" aria-hidden="true" />
          Course
          {hasIls === false && <span className="pos-mono pos-bottombar__na"> n/a</span>}
        </label>
        <label
          className={ilsKnown ? 'pos-checkbox' : 'pos-checkbox pos-checkbox--disabled'}
        >
          <input
            type="checkbox"
            className="pos-checkbox__input"
            checked={send.ilsFrequency}
            disabled={!ilsKnown}
            onChange={() => {
              dispatch(sendToggled('ilsFrequency'));
            }}
          />
          <span className="pos-checkbox__box" aria-hidden="true" />
          ILS frequency
          {hasIls === false && <span className="pos-mono pos-bottombar__na"> n/a</span>}
        </label>
        <button
          ref={startAtTriggerRef}
          type="button"
          className="pos-textaction pos-bottombar__startat"
          aria-haspopup="dialog"
          aria-expanded={startAtOpen}
          aria-controls={startAtPopoverId('bottombar')}
          onClick={() => {
            dispatch(startAtToggled('bottombar'));
          }}
        >
          Pick stand / gate{' '}
          <span className="pos-mono">
            {startAtLabelOf(selectedRunway, selectedStand)}
          </span>
        </button>
        <StartAtPopover anchor="bottombar" triggerRef={startAtTriggerRef} />
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
          Open map
        </button>
        <div className="pos-bottombar__commit">
          {!gate.open && <p className="pos-bottombar__blocked">{gate.reason}</p>}
          {request === null && gate.open && (
            <p className="pos-bottombar__blocked">
              Nothing to place yet — load an airport and pick a start position.
            </p>
          )}
          {speedReason !== null && gate.open && request !== null && (
            <p className="pos-bottombar__blocked">{speedReason}</p>
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
