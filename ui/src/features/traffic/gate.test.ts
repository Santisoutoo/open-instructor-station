/**
 * The traffic gate must **fail closed** — the moments before an answer arrives and the
 * moments when no answer will are the interesting ones, not the happy path. This is the
 * UI half of Phase 3 exit criterion 3: with the bridge absent the adapter does not
 * declare `can_spawn_traffic`, and the controls disable with a stated reason.
 */

import { describe, expect, it } from 'vitest';
import type { Capabilities } from '../../api/models';
import { trafficGate } from './gate';

function capabilities(overrides: Partial<Capabilities> = {}): Capabilities {
  return {
    can_set_position: false,
    can_set_aircraft_state: false,
    can_set_weather: false,
    can_inject_failures: false,
    can_spawn_traffic: true,
    can_control_autopilot: false,
    can_set_fuel_payload: false,
    can_control_camera: false,
    can_pushback: false,
    ...overrides,
  };
}

describe('trafficGate', () => {
  it('is closed while the capabilities are still loading', () => {
    const gate = trafficGate(undefined, false);

    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/waiting/i);
  });

  it('is closed when the capabilities could not be read at all', () => {
    const gate = trafficGate(undefined, true);

    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/could not be read/i);
  });

  it('names the missing capability rather than saying "unavailable"', () => {
    const gate = trafficGate(capabilities({ can_spawn_traffic: false }), false);

    expect(gate.open).toBe(false);
    expect(gate.reason).toContain('can_spawn_traffic');
  });

  it('says the bridge is what is missing, because that is the fix', () => {
    const gate = trafficGate(capabilities({ can_spawn_traffic: false }), false);

    expect(gate.reason).toMatch(/bridge/i);
  });

  it('opens once the adapter declares can_spawn_traffic', () => {
    expect(trafficGate(capabilities(), false)).toEqual({ open: true, reason: '' });
  });
});
