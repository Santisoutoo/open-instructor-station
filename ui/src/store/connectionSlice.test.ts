import { describe, expect, it } from 'vitest';
import reducer, {
  connectionClosed,
  connectionEstablished,
  connectionFailed,
  connectionOpening,
  initialConnectionState,
} from './connectionSlice';
import { telemetryFrameReceived } from '../features/telemetry/telemetrySlice';
import type { AircraftState } from '../api/types';

const SAMPLE: AircraftState = {
  latitude: 47.44712,
  longitude: -122.30931,
  altitude_ft: 433,
  heading_deg: 160,
  ias_kt: 0,
  vertical_speed_fpm: 0,
  pitch_deg: 0,
  roll_deg: 0,
  on_ground: true,
};

describe('connectionSlice', () => {
  it('starts idle with no error and no recorded update', () => {
    expect(reducer(undefined, { type: '@@INIT' })).toEqual(initialConnectionState);
  });

  it('walks through connecting -> connected and clears the previous error', () => {
    const failed = reducer(initialConnectionState, connectionFailed('code 1006'));
    expect(failed.status).toBe('error');
    expect(failed.lastError).toBe('code 1006');
    expect(failed.reconnectAttempts).toBe(1);

    const connecting = reducer(failed, connectionOpening());
    expect(connecting.status).toBe('connecting');
    // The error text survives the retry so the badge can keep explaining itself.
    expect(connecting.lastError).toBe('code 1006');

    const connected = reducer(connecting, connectionEstablished());
    expect(connected.status).toBe('connected');
    expect(connected.lastError).toBeNull();
    expect(connected.reconnectAttempts).toBe(0);
  });

  it('counts consecutive failures for the reconnect backoff', () => {
    const once = reducer(initialConnectionState, connectionFailed('boom'));
    const twice = reducer(once, connectionFailed('boom again'));
    expect(twice.reconnectAttempts).toBe(2);
    expect(twice.lastError).toBe('boom again');
  });

  it('stamps lastUpdateAt from telemetry frames without owning the feed', () => {
    const connected = reducer(initialConnectionState, connectionEstablished());
    expect(connected.lastUpdateAt).toBeNull();

    const updated = reducer(
      connected,
      telemetryFrameReceived({ state: SAMPLE, receivedAt: 1_700_000_000_000 }),
    );
    expect(updated.lastUpdateAt).toBe(1_700_000_000_000);
    expect(updated.status).toBe('connected');
  });

  it('goes back to idle when the socket is closed deliberately', () => {
    const connected = reducer(initialConnectionState, connectionEstablished());
    expect(reducer(connected, connectionClosed()).status).toBe('idle');
  });
});
