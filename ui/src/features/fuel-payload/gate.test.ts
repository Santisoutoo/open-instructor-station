/**
 * The Fuel & Payload gate must fail **closed**.
 *
 * The interesting cases are not the happy ones — they are the moments before the
 * manifest arrives and the moments when it never will. Hard rule 3 is only real if
 * "I could not find out" disables; otherwise a slow or unreachable server reads as
 * fully capable and the panel offers a button that cannot work.
 */

import { describe, expect, it } from 'vitest';
import type { FuelPayloadManifest } from '../../api/models';
import { fuelPayloadGate } from './gate';

function manifest(overrides: Partial<FuelPayloadManifest> = {}): FuelPayloadManifest {
  return {
    adapter: 'fake',
    supported: true,
    reason: null,
    icao_type: 'C172',
    limits_source: 'table',
    limits_note: 'Illustrative C172S figures.',
    limits: null,
    tank_count: 2,
    station_count: 3,
    presets: [],
    ...overrides,
  };
}

describe('fuelPayloadGate', () => {
  it('is closed while the manifest is still loading', () => {
    const gate = fuelPayloadGate(undefined, false);

    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/reading/i);
  });

  it('is closed when the manifest could not be read at all', () => {
    const gate = fuelPayloadGate(undefined, true);

    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/could not be read/i);
  });

  it('is closed and names the reason when the adapter does not support it', () => {
    const gate = fuelPayloadGate(
      manifest({
        supported: false,
        reason: "The 'xplane' adapter does not declare can_set_fuel_payload.",
      }),
      false,
    );

    expect(gate.open).toBe(false);
    expect(gate.reason).toContain('can_set_fuel_payload');
  });

  it('falls back to a generic reason when the manifest states none', () => {
    const gate = fuelPayloadGate(manifest({ supported: false, reason: null }), false);

    expect(gate.open).toBe(false);
    expect(gate.reason.length).toBeGreaterThan(0);
  });

  it('opens when the manifest reports support', () => {
    expect(fuelPayloadGate(manifest(), false)).toEqual({ open: true, reason: '' });
  });
});
