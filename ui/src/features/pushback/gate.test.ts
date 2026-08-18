/**
 * The pushback gate must **fail closed** — the moments before an answer arrives and
 * the moments when no answer will are the interesting ones, not the happy path.
 */

import { describe, expect, it } from 'vitest';
import type { Capabilities } from '../../api/models';
import { pushbackGate } from './gate';

function capabilities(overrides: Partial<Capabilities> = {}): Capabilities {
  return {
    can_set_position: false,
    can_set_aircraft_state: false,
    can_set_weather: false,
    can_inject_failures: false,
    can_spawn_traffic: false,
    can_control_autopilot: false,
    can_set_fuel_payload: false,
    can_control_camera: false,
    can_pushback: true,
    ...overrides,
  };
}

describe('pushbackGate', () => {
  it('is closed while the capabilities are still loading', () => {
    const gate = pushbackGate(undefined, false);

    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/waiting/i);
  });

  it('is closed when the capabilities could not be read at all', () => {
    const gate = pushbackGate(undefined, true);

    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/could not be read/i);
  });

  it('names the missing capability rather than saying "unavailable"', () => {
    const gate = pushbackGate(capabilities({ can_pushback: false }), false);

    expect(gate.open).toBe(false);
    expect(gate.reason).toContain('can_pushback');
  });

  it('opens once the adapter declares can_pushback', () => {
    expect(pushbackGate(capabilities(), false)).toEqual({ open: true, reason: '' });
  });
});
