/**
 * The traffic gate must **fail closed**.
 *
 * Hard rule 3 is only real if "I could not find out" counts as unsupported: a manifest
 * that is still loading, or that could not be read at all, disables the panel exactly
 * like an explicit `available: false` does. The happy path is the least interesting
 * case here.
 */

import { describe, expect, it } from 'vitest';
import { trafficGate } from './gate';
import type { TrafficManifest } from './types.mock';

function manifest(overrides: Partial<TrafficManifest> = {}): TrafficManifest {
  return { available: true, reason: null, bridge: 'connected (demo)', ...overrides };
}

describe('trafficGate', () => {
  it('is closed while the manifest is still loading', () => {
    const gate = trafficGate(undefined, false);

    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/waiting/i);
  });

  it('is closed when the manifest could not be read at all', () => {
    const gate = trafficGate(undefined, true);

    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/could not be read/i);
  });

  it('shows the bridge reason verbatim when the bridge says no', () => {
    const gate = trafficGate(
      manifest({ available: false, reason: 'The bridge plugin is not connected.' }),
      false,
    );

    expect(gate.open).toBe(false);
    expect(gate.reason).toBe('The bridge plugin is not connected.');
  });

  it('names the missing capability when no reason was given', () => {
    const gate = trafficGate(manifest({ available: false, reason: null }), false);

    expect(gate.open).toBe(false);
    expect(gate.reason).toContain('can_spawn_traffic');
  });

  it('opens only on an explicit available manifest, with an empty reason', () => {
    expect(trafficGate(manifest(), false)).toEqual({ open: true, reason: '' });
  });
});
