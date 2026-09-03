/**
 * The failures gate must **fail closed** — the moments before an answer arrives and the
 * moments when no answer will are the interesting ones, not the happy path.
 */

import { describe, expect, it } from 'vitest';
import type { Capabilities } from '../../api/models';
import { failuresGate } from './gate';

function capabilities(overrides: Partial<Capabilities> = {}): Capabilities {
  return {
    can_set_position: false,
    can_set_aircraft_state: false,
    can_set_weather: false,
    can_inject_failures: true,
    can_spawn_traffic: false,
    can_control_autopilot: false,
    can_set_fuel_payload: false,
    can_control_camera: false,
    can_pushback: false,
    can_control_cockpit: false,
    ...overrides,
  };
}

describe('failuresGate', () => {
  it('is closed while the capabilities are still loading', () => {
    const gate = failuresGate(undefined, false);

    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/waiting/i);
  });

  it('is closed when the capabilities could not be read at all', () => {
    const gate = failuresGate(undefined, true);

    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/could not be read/i);
  });

  it('names the missing capability rather than saying "unavailable"', () => {
    const gate = failuresGate(capabilities({ can_inject_failures: false }), false);

    expect(gate.open).toBe(false);
    expect(gate.reason).toContain('can_inject_failures');
  });

  it('opens once the adapter declares can_inject_failures', () => {
    expect(failuresGate(capabilities(), false)).toEqual({ open: true, reason: '' });
  });
});
