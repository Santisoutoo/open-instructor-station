import { describe, expect, it } from 'vitest';
import reducer, {
  aircraftControlsReset,
  controlErrorDismissed,
  controlWriteFailed,
  controlWriteStarted,
  controlWriteSucceeded,
  initialAircraftControlsState,
  selectControlValue,
  selectIsPending,
  type AircraftControlsState,
} from './aircraftSlice';
import { telemetryCleared } from '../telemetry/telemetrySlice';

describe('aircraftSlice', () => {
  it('starts with nothing commanded and nothing in flight', () => {
    expect(reducer(undefined, { type: '@@INIT' })).toEqual(initialAircraftControlsState);
  });

  it('shows a started write optimistically before the server has answered', () => {
    const state = reducer(undefined, controlWriteStarted({ key: 'gear', value: true }));

    expect(selectControlValue(state, 'gear')).toBe(true);
    expect(selectIsPending(state, 'gear')).toBe(true);
    expect(state.commanded['gear']).toBeUndefined();
  });

  it('promotes a pending write to commanded once the server confirms it', () => {
    let state = reducer(undefined, controlWriteStarted({ key: 'flaps', value: 0.5 }));
    state = reducer(state, controlWriteSucceeded({ key: 'flaps', value: 0.5 }));

    expect(selectIsPending(state, 'flaps')).toBe(false);
    expect(state.commanded['flaps']).toBe(0.5);
    expect(selectControlValue(state, 'flaps')).toBe(0.5);
    expect(state.lastError).toBeNull();
  });

  it('drops the optimistic value when the write fails, rather than lying about it', () => {
    let state = reducer(undefined, controlWriteStarted({ key: 'gear', value: true }));
    state = reducer(
      state,
      controlWriteFailed({ key: 'gear', message: 'Adapter said no.' }),
    );

    expect(selectIsPending(state, 'gear')).toBe(false);
    expect(selectControlValue(state, 'gear')).toBeUndefined();
    expect(state.lastError).toBe('Adapter said no.');
  });

  it('keeps the previously confirmed value when a later write fails', () => {
    let state = reducer(undefined, controlWriteSucceeded({ key: 'flaps', value: 0.25 }));
    state = reducer(state, controlWriteStarted({ key: 'flaps', value: 1 }));
    expect(selectControlValue(state, 'flaps')).toBe(1);

    state = reducer(state, controlWriteFailed({ key: 'flaps', message: 'Rejected.' }));
    expect(selectControlValue(state, 'flaps')).toBe(0.25);
  });

  it('tracks the light switches independently of each other', () => {
    let state = reducer(
      undefined,
      controlWriteSucceeded({ key: 'lights_landing', value: true }),
    );
    state = reducer(state, controlWriteSucceeded({ key: 'lights_strobe', value: false }));

    expect(selectControlValue(state, 'lights_landing')).toBe(true);
    expect(selectControlValue(state, 'lights_strobe')).toBe(false);
    expect(selectControlValue(state, 'lights_beacon')).toBeUndefined();
  });

  it('clears the error banner without touching any control', () => {
    let state = reducer(undefined, controlWriteSucceeded({ key: 'gear', value: true }));
    state = reducer(state, controlWriteFailed({ key: 'flaps', message: 'Rejected.' }));
    state = reducer(state, controlErrorDismissed());

    expect(state.lastError).toBeNull();
    expect(selectControlValue(state, 'gear')).toBe(true);
  });

  it('starting a new write clears a stale error', () => {
    let state = reducer(
      undefined,
      controlWriteFailed({ key: 'gear', message: 'Rejected.' }),
    );
    state = reducer(state, controlWriteStarted({ key: 'gear', value: true }));

    expect(state.lastError).toBeNull();
  });

  it('forgets everything when the telemetry link drops', () => {
    // A "gear down" the station commanded before losing sight of the aircraft is no
    // longer evidence of anything.
    const commanded: AircraftControlsState = reducer(
      undefined,
      controlWriteSucceeded({ key: 'gear', value: true }),
    );

    expect(reducer(commanded, telemetryCleared())).toEqual(initialAircraftControlsState);
  });

  it('is reset explicitly too', () => {
    const state = reducer(undefined, controlWriteSucceeded({ key: 'gear', value: true }));
    expect(reducer(state, aircraftControlsReset())).toEqual(initialAircraftControlsState);
  });
});
