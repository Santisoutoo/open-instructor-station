/**
 * The pushback gate must **fail closed** — the moments before an answer arrives and
 * the moments when no answer will are the interesting ones, not the happy path.
 *
 * It also carries the slider bounds out of the manifest, which is the other half of its
 * job: an open gate is the only state in which the panel has a ceiling to clamp against,
 * so the panel never needs a constant of its own.
 */

import { describe, expect, it } from 'vitest';
import type { PushbackManifest } from '../../api/models';
import { pushbackGate } from './gate';

function manifest(overrides: Partial<PushbackManifest> = {}): PushbackManifest {
  return {
    adapter: 'fake',
    supported: true,
    reason: null,
    max_distance_m: 200,
    max_angle_deg: 180,
    ...overrides,
  };
}

describe('pushbackGate', () => {
  it('is closed while the manifest is still loading', () => {
    const gate = pushbackGate(undefined, false);

    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/waiting/i);
    expect(gate.maxDistanceM).toBeUndefined();
  });

  it('is closed when the manifest could not be read at all', () => {
    const gate = pushbackGate(undefined, true);

    expect(gate.open).toBe(false);
    expect(gate.reason).toMatch(/could not be read/i);
  });

  it("shows the server's own sentence when the adapter cannot push back", () => {
    const gate = pushbackGate(
      manifest({
        adapter: 'xplane',
        supported: false,
        reason: "The 'xplane' adapter does not declare can_pushback.",
      }),
      false,
    );

    expect(gate.open).toBe(false);
    // Verbatim: the server names the adapter and the flag, and the UI invents nothing.
    expect(gate.reason).toBe("The 'xplane' adapter does not declare can_pushback.");
  });

  it('still names the missing capability when the server sent no reason', () => {
    const gate = pushbackGate(manifest({ supported: false, reason: null }), false);

    expect(gate.open).toBe(false);
    expect(gate.reason).toContain('can_pushback');
  });

  it('opens with the bounds the manifest stated — not with a copy of them', () => {
    expect(pushbackGate(manifest({ max_distance_m: 50, max_angle_deg: 90 }), false)).toEqual({
      open: true,
      reason: '',
      maxDistanceM: 50,
      maxAngleDeg: 90,
    });
  });

  it('leaves the bounds unset while closed — there is nothing to have read them from', () => {
    const gate = pushbackGate(manifest({ supported: false }), false);

    expect(gate.maxDistanceM).toBeUndefined();
    expect(gate.maxAngleDeg).toBeUndefined();
  });
});
