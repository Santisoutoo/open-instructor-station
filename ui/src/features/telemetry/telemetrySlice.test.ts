import { describe, expect, it } from 'vitest';
import reducer, {
  initialTelemetryState,
  telemetryCleared,
  telemetryFrameReceived,
} from './telemetrySlice';
import { isAircraftState, type AircraftState } from '../../api/models';

const CRUISE: AircraftState = {
  latitude: 47.44712,
  longitude: -122.30931,
  altitude_ft: 12_500.4,
  heading_deg: 47.2,
  ias_kt: 243.6,
  vertical_speed_fpm: 1800,
  pitch_deg: 2.5,
  roll_deg: -1.25,
  on_ground: false,
};

describe('telemetrySlice', () => {
  it('starts empty', () => {
    expect(reducer(undefined, { type: '@@INIT' })).toEqual(initialTelemetryState);
  });

  it('keeps only the latest frame and counts what it accepted', () => {
    const first = reducer(
      undefined,
      telemetryFrameReceived({ state: CRUISE, receivedAt: 1000 }),
    );
    expect(first.latest).toEqual(CRUISE);
    expect(first.receivedAt).toBe(1000);
    expect(first.frameCount).toBe(1);

    const descending: AircraftState = { ...CRUISE, altitude_ft: 9000, ias_kt: 210 };
    const second = reducer(
      first,
      telemetryFrameReceived({ state: descending, receivedAt: 1250 }),
    );
    expect(second.latest).toEqual(descending);
    expect(second.receivedAt).toBe(1250);
    expect(second.frameCount).toBe(2);
  });

  it('drops the stale state when the link is cleared', () => {
    const populated = reducer(
      undefined,
      telemetryFrameReceived({ state: CRUISE, receivedAt: 1000 }),
    );
    expect(reducer(populated, telemetryCleared())).toEqual(initialTelemetryState);
  });
});

describe('isAircraftState', () => {
  it('accepts a well-formed frame', () => {
    expect(isAircraftState(CRUISE)).toBe(true);
  });

  it('rejects malformed WebSocket payloads', () => {
    expect(isAircraftState(null)).toBe(false);
    expect(isAircraftState('not json')).toBe(false);
    expect(isAircraftState({ ...CRUISE, on_ground: 'false' })).toBe(false);
    expect(isAircraftState({ ...CRUISE, altitude_ft: null })).toBe(false);
    expect(isAircraftState({ ...CRUISE, latitude: Number.NaN })).toBe(false);
    const { roll_deg: _omitted, ...missingField } = CRUISE;
    expect(isAircraftState(missingField)).toBe(false);
  });
});
