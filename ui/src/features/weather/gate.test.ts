/**
 * Both gates must **fail closed** — the same discipline `features/position/gate.test.ts`
 * holds its gates to. `weatherGate` checks the capability before the read, so an
 * unsupported adapter reads as "unsupported" and not as a generic, retry-shaped failure.
 */

import { describe, expect, it } from 'vitest';
import type { Capabilities, WeatherPresetInfo, WeatherState } from '../../api/models';
import { presetGate, weatherGate } from './gate';

function capabilities(overrides: Partial<Capabilities> = {}): Capabilities {
  return {
    can_set_position: true,
    can_set_aircraft_state: true,
    can_set_weather: true,
    can_inject_failures: false,
    can_spawn_traffic: false,
    can_control_autopilot: false,
    can_set_fuel_payload: false,
    can_control_camera: false,
    can_pushback: false,
    ...overrides,
  };
}

function currentState(): WeatherState {
  return {
    wind_layers: [],
    cloud_layers: [],
    visibility_m: 10000,
    qnh_hpa: 1013,
    temperature_c: 15,
    dewpoint_c: 5,
    precipitation_ratio: 0,
    runway_contamination: 'dry',
  };
}

function preset(overrides: Partial<WeatherPresetInfo> = {}): WeatherPresetInfo {
  return {
    id: 'cavok',
    label: 'CAVOK',
    description: '',
    requires_runway: false,
    requires_airport: false,
    ...overrides,
  };
}

describe('weatherGate', () => {
  it('is closed while the capabilities are still loading', () => {
    const gate = weatherGate(undefined, false, undefined, false);
    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/waiting/i);
  });

  it('is closed when the capabilities could not be read at all', () => {
    const gate = weatherGate(undefined, true, undefined, false);
    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/could not be read/i);
  });

  it('names the missing capability rather than a generic failure', () => {
    const gate = weatherGate(capabilities({ can_set_weather: false }), false, undefined, false);
    expect(gate.open).toBe(false);
    expect(gate.reason).toContain('can_set_weather');
  });

  it('is closed while the current weather is still loading, even with the capability', () => {
    const gate = weatherGate(capabilities(), false, undefined, false);
    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/reading/i);
  });

  it('is closed when the current weather could not be read', () => {
    const gate = weatherGate(capabilities(), false, undefined, true);
    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/could not be read/i);
  });

  it('opens once both the capability and the current weather are in', () => {
    expect(weatherGate(capabilities(), false, currentState(), false)).toEqual({
      open: true,
      reason: '',
    });
  });
});

describe('presetGate', () => {
  it('opens a preset that needs neither a runway nor an airport', () => {
    expect(presetGate(preset(), null, null)).toEqual({ open: true, reason: '' });
  });

  it('blocks a runway-relative preset without a runway, and says why', () => {
    const gate = presetGate(preset({ requires_runway: true, requires_airport: true }), null, null);
    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/runway/i);
  });

  it('blocks an airport-relative preset without an airport, and says why', () => {
    const gate = presetGate(preset({ requires_airport: true }), null, null);
    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/airport/i);
  });

  it('opens a runway-relative preset once both are selected', () => {
    const gate = presetGate(
      preset({ requires_runway: true, requires_airport: true }),
      'LEMD',
      '32L',
    );
    expect(gate).toEqual({ open: true, reason: '' });
  });

  it('opens an airport-relative (not runway-relative) preset with only an airport', () => {
    const gate = presetGate(preset({ requires_airport: true }), 'LEMD', null);
    expect(gate).toEqual({ open: true, reason: '' });
  });
});
