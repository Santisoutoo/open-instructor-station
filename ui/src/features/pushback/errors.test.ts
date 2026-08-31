/**
 * The one thing this module exists for: 501 and 409 must never come out the same.
 *
 * `server/pushback_routes.py` chose two different statuses deliberately — a capability
 * answer and a state precondition — and a UI that mapped both to "pushback failed" would
 * throw that away, disabling the panel for the session over an aircraft that is simply
 * airborne at this instant.
 */

import { describe, expect, it } from 'vitest';
import { describePushbackRefusal, disablesPushback } from './errors';

function fetchError(status: number, detail?: string) {
  return { status, data: detail === undefined ? {} : { detail } };
}

describe('describePushbackRefusal', () => {
  it('reads 501 as a capability answer', () => {
    const refusal = describePushbackRefusal(
      fetchError(
        501,
        "Unavailable on this adapter — the 'xplane' adapter does not declare can_pushback, " +
          'so it cannot push the aircraft back.',
      ),
    );

    expect(refusal.kind).toBe('unsupported');
    expect(refusal.message).toContain('can_pushback');
  });

  it('reads 409 as a state precondition, NOT as an unsupported adapter', () => {
    const refusal = describePushbackRefusal(
      fetchError(409, 'Cannot push back — the aircraft is airborne.'),
    );

    expect(refusal.kind).toBe('not-on-ground');
    expect(refusal.message).toBe('Cannot push back — the aircraft is airborne.');
  });

  it('keeps the two apart even when the server sends no detail at all', () => {
    const unsupported = describePushbackRefusal(fetchError(501));
    const airborne = describePushbackRefusal(fetchError(409));

    expect(unsupported.kind).not.toBe(airborne.kind);
    expect(unsupported.message).not.toBe(airborne.message);
  });

  it('falls back without inventing a diagnosis when nothing came back', () => {
    const refusal = describePushbackRefusal({ status: 'FETCH_ERROR', error: 'boom' });

    expect(refusal.kind).toBe('unknown');
    expect(refusal.message).toMatch(/did not answer/i);
  });

  it('prefers the server sentence over its own for anything else, e.g. a 422', () => {
    const refusal = describePushbackRefusal(
      fetchError(422, "direction='left' needs angle_deg > 0."),
    );

    expect(refusal.kind).toBe('unknown');
    expect(refusal.message).toBe("direction='left' needs angle_deg > 0.");
  });
});

describe('disablesPushback', () => {
  it('disables the panel only for a missing capability', () => {
    expect(disablesPushback(describePushbackRefusal(fetchError(501)))).toBe(true);
  });

  it('does NOT disable it for an airborne aircraft — that clears on touchdown', () => {
    expect(disablesPushback(describePushbackRefusal(fetchError(409)))).toBe(false);
  });

  it('does NOT disable it for a dropped connection either — a blip is not a verdict', () => {
    // The trap this predicate exists to avoid: lumping "no answer" in with "no
    // capability" would strand the instructor with no way out but a page reload.
    const dropped = describePushbackRefusal({ status: 'FETCH_ERROR', error: 'boom' });

    expect(dropped.kind).toBe('unknown');
    expect(disablesPushback(dropped)).toBe(false);
  });

  it('is false when nothing was refused', () => {
    expect(disablesPushback(null)).toBe(false);
  });
});
