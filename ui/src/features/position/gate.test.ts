/**
 * Both gates must **fail closed**.
 *
 * The interesting cases are not the happy ones — they are the moments before an answer
 * arrives and the moments when no answer will. Hard rule 3 is only real if "I could not
 * find out" disables; otherwise a slow or unreachable server reads as fully capable and
 * the panel offers a button that cannot work.
 */

import { describe, expect, it } from 'vitest';
import type { Capabilities, NavdataStatus } from '../../api/models';
import { airacLabel, commitGate, navdataGate } from './gate';

function capabilities(overrides: Partial<Capabilities> = {}): Capabilities {
  return {
    can_set_position: true,
    can_set_aircraft_state: true,
    can_set_weather: false,
    can_inject_failures: false,
    can_spawn_traffic: false,
    can_control_autopilot: false,
    can_set_fuel_payload: false,
    can_control_camera: false,
    can_pushback: false,
    can_control_cockpit: false,
    ...overrides,
  };
}

function status(overrides: Partial<NavdataStatus> = {}): NavdataStatus {
  return { state: 'ready', provider: 'in_memory', ...overrides };
}

describe('commitGate', () => {
  it('is closed while the capabilities are still loading', () => {
    const gate = commitGate(undefined, false);

    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/waiting/i);
  });

  it('is closed when the capabilities could not be read at all', () => {
    const gate = commitGate(undefined, true);

    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/could not be read/i);
  });

  it('names the missing capability rather than saying "unavailable"', () => {
    const gate = commitGate(capabilities({ can_set_position: false }), false);

    expect(gate.open).toBe(false);
    expect(gate.reason).toContain('can_set_position');
  });

  it('is closed when the adapter cannot write the state a placement needs', () => {
    // Every placement writes a speed before the teleport; without that an aircraft put
    // on a final arrives below stall speed.
    const gate = commitGate(capabilities({ can_set_aircraft_state: false }), false);

    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/speed or altitude/i);
  });

  it('opens only when both capabilities are declared', () => {
    expect(commitGate(capabilities(), false)).toEqual({ open: true, reason: '' });
  });
});

describe('navdataGate', () => {
  it('is loading, not blocked, before the first answer', () => {
    expect(navdataGate(undefined, false).kind).toBe('loading');
  });

  it('blocks without a build button when the status itself could not be read', () => {
    const gate = navdataGate(undefined, true);

    expect(gate).toMatchObject({ kind: 'blocked', canBuild: false });
  });

  it('passes a ready provider straight through', () => {
    expect(navdataGate(status(), false)).toEqual({ kind: 'ready' });
  });

  it('offers to build an index that has never been built', () => {
    const gate = navdataGate(
      status({ state: 'unavailable', reason: 'No index yet.' }),
      false,
    );

    expect(gate).toEqual({ kind: 'blocked', reason: 'No index yet.', canBuild: true });
  });

  it('does not offer to re-run a build that failed', () => {
    // It would fail the same way until the underlying problem is fixed, and a button
    // that repeats a known failure is worse than the sentence explaining it.
    const gate = navdataGate(
      status({ state: 'error', reason: 'apt.dat is unreadable.' }),
      false,
    );

    expect(gate).toMatchObject({ kind: 'blocked', canBuild: false });
  });

  it('reports build progress from the published frame', () => {
    const gate = navdataGate(
      status({
        state: 'building',
        progress: {
          stage: 'airports',
          stage_index: 1,
          stage_count: 6,
          fraction: 0.25,
          detail: 'apt.dat — 3.1 M / 12.4 M lines',
        },
      }),
      false,
    );

    expect(gate).toEqual({
      kind: 'building',
      reason: 'apt.dat — 3.1 M / 12.4 M lines',
      fraction: 0.25,
    });
  });

  it('still reports building when the provider published no progress frame', () => {
    const gate = navdataGate(status({ state: 'building' }), false);

    expect(gate).toMatchObject({ kind: 'building', fraction: null });
  });
});

describe('airacLabel', () => {
  it('is null when the provider publishes no cycle', () => {
    expect(airacLabel(status())).toBeNull();
    expect(airacLabel(undefined)).toBeNull();
  });

  it('labels the cycle when there is one', () => {
    expect(airacLabel(status({ airac_cycle: '2607' }))).toBe('AIRAC 2607');
  });
});
