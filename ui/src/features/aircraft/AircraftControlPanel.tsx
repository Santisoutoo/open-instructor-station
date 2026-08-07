import {
  useApplyAircraftSetupMutation,
  useGetAircraftControlsQuery,
} from '../../api/instructorApi';
import type { AircraftSetup, ControlId } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import {
  controlErrorDismissed,
  controlWriteFailed,
  controlWriteStarted,
  controlWriteSucceeded,
  selectControlValue,
  selectIsPending,
} from './aircraftSlice';
import {
  CONTROL_DISPLAY,
  CONTROL_SECTIONS,
  LIGHT_SWITCHES,
  controlAvailability,
  type ControlAvailability,
  type ControlValue,
  type WriteKey,
} from './controls';
import { SliderControl, StepperControl, ToggleControl } from './ControlWidgets';

/** Turns whatever RTK Query hands back into one line an instructor can act on. */
function describeWriteError(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'data' in error) {
    const data = (error as { data?: unknown }).data;
    if (typeof data === 'object' && data !== null && 'detail' in data) {
      const detail = (data as { detail?: unknown }).detail;
      if (typeof detail === 'string') {
        return detail;
      }
    }
  }
  if (typeof error === 'object' && error !== null && 'status' in error) {
    return `The write was rejected (${String((error as { status: unknown }).status)}).`;
  }
  return 'The write did not reach the instructor server.';
}

/**
 * Manager 6 — live Aircraft Control.
 *
 * Reads and writes take deliberately different routes, as the feature spec requires:
 * the live picture arrives on the `/ws/state` WebSocket (already in the telemetry slice),
 * every write is an idempotent `POST /api/aircraft/setup`.
 *
 * Every control is gated on `GET /api/aircraft/controls` and **fails closed**: while the
 * manifest is loading, if it cannot be read, or if the server reports a control as
 * unsupported, the widget renders disabled with the server's own reason next to it. The
 * panel never calls an endpoint the adapter cannot honour.
 */
export function AircraftControlPanel() {
  const dispatch = useAppDispatch();
  const { data: manifest, isError } = useGetAircraftControlsQuery();
  const [applySetup] = useApplyAircraftSetupMutation();

  const live = useAppSelector((state) => state.telemetry.latest);
  const controls = useAppSelector((state) => state.aircraft);

  /** Optimistically apply, then confirm or roll back against the server's answer. */
  const write = async (key: WriteKey, value: ControlValue, setup: AircraftSetup) => {
    dispatch(controlWriteStarted({ key, value }));
    try {
      await applySetup(setup).unwrap();
      dispatch(controlWriteSucceeded({ key, value }));
    } catch (error) {
      dispatch(controlWriteFailed({ key, message: describeWriteError(error) }));
    }
  };

  const renderControl = (id: ControlId) => {
    const display = CONTROL_DISPLAY[id];
    const availability: ControlAvailability = controlAvailability(id, manifest, isError);
    const disabled = !availability.writable;

    if (display.kind === 'lights') {
      return (
        <fieldset className="control control--lights" key={id} disabled={disabled}>
          <legend className="control__label">{display.label}</legend>
          <div className="control__switches">
            {LIGHT_SWITCHES.map((light) => {
              const key: WriteKey = `lights_${light.name}`;
              const value = selectControlValue(controls, key);
              const on = value === true;
              return (
                <button
                  key={light.name}
                  className={`control__toggle control__toggle--${on ? 'on' : 'off'}`}
                  type="button"
                  aria-pressed={on}
                  disabled={disabled || selectIsPending(controls, key)}
                  onClick={() => {
                    void write(key, !on, light.toSetup(!on));
                  }}
                >
                  {light.label}
                </button>
              );
            })}
          </div>
          {disabled && <p className="control__hint">{availability.reason}</p>}
        </fieldset>
      );
    }

    const pending = selectIsPending(controls, id);
    const commanded = selectControlValue(controls, id);

    if (display.kind === 'toggle') {
      return (
        <ToggleControl
          key={id}
          display={display}
          value={typeof commanded === 'boolean' ? commanded : null}
          disabled={disabled}
          reason={availability.reason}
          pending={pending}
          onCommit={(next) => {
            if (display.toSetup !== null) {
              void write(id, next, display.toSetup(next));
            }
          }}
        />
      );
    }

    // Numeric widgets prefer the live feed where the aircraft actually reports the value,
    // and fall back to the last confirmed command where it does not (flaps, autobrake).
    const liveValue =
      display.readLive !== null && live !== null ? display.readLive(live) : null;
    const value = pending
      ? (commanded ?? liveValue)
      : (liveValue ?? (typeof commanded === 'number' ? commanded : null));
    const numeric = typeof value === 'number' ? value : null;

    const onCommit = (next: number) => {
      if (display.toSetup !== null) {
        void write(id, next, display.toSetup(next));
      }
    };

    return display.kind === 'slider' ? (
      <SliderControl
        key={id}
        display={display}
        value={numeric}
        disabled={disabled}
        reason={availability.reason}
        pending={pending}
        onCommit={onCommit}
      />
    ) : (
      <StepperControl
        key={id}
        display={display}
        value={numeric}
        disabled={disabled}
        reason={availability.reason}
        pending={pending}
        onCommit={onCommit}
      />
    );
  };

  return (
    <section className="panel panel--wide" aria-labelledby="aircraft-heading">
      <h2 id="aircraft-heading">Aircraft control</h2>

      {isError && (
        <p className="panel__error" role="alert">
          The control manifest is unavailable — every control stays disabled.
        </p>
      )}

      {controls.lastError !== null && (
        <p className="panel__error" role="alert">
          {controls.lastError}{' '}
          <button
            className="control__dismiss"
            type="button"
            onClick={() => dispatch(controlErrorDismissed())}
          >
            Dismiss
          </button>
        </p>
      )}

      {CONTROL_SECTIONS.map((section) => {
        const headingId = `aircraft-group-${section.title.toLowerCase().replace(/\s+/g, '-')}`;
        return (
          <section
            className="control-group"
            key={section.title}
            aria-labelledby={headingId}
          >
            <h3 className="control-group__title" id={headingId}>
              {section.title}
            </h3>
            <div className="control-group__body">
              {section.controls.map(renderControl)}
            </div>
          </section>
        );
      })}
    </section>
  );
}
