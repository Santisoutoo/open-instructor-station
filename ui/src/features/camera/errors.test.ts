/**
 * The four failures of §2.1/§2.2 must stay four failures.
 *
 * The interesting property is not the wording — the server owns that — but the *kind*:
 * a 409 is a precondition the instructor can clear in one tap, and telling them it is an
 * unsupported capability would send them away from something that works. So each status
 * is pinned to its own kind, and the two that share a colour still differ in kind.
 */

import { describe, expect, it } from 'vitest';
import { cameraError } from './errors';

/** What `fetchBaseQuery` hands a component for a FastAPI error response. */
function httpError(status: number, detail: unknown): unknown {
  return { status, data: { detail } };
}

const FALLBACK = 'The camera request failed.';

describe('cameraError', () => {
  it('reads a 501 as a permanent capability refusal, in the adapter’s own words', () => {
    const detail =
      "Unavailable on this adapter — the 'xplane' adapter does not declare " +
      'can_control_camera, so it cannot control the camera.';

    expect(cameraError(httpError(501, detail), FALLBACK)).toEqual({
      kind: 'unsupported',
      message: detail,
    });
  });

  it('reads a 409 as a temporary precondition, never as unsupported', () => {
    const detail =
      'Cannot save a camera position right now — switch to the drone/free camera first.';
    const error = cameraError(httpError(409, detail), FALLBACK);

    expect(error).toEqual({ kind: 'precondition', message: detail });
    // The distinction the panel depends on, stated as its own assertion.
    expect(error.kind).not.toBe('unsupported');
  });

  it('reads a 404 as an unknown saved id', () => {
    const detail = "No saved camera position 'gone' — it may already be deleted.";

    expect(cameraError(httpError(404, detail), FALLBACK)).toEqual({
      kind: 'missing',
      message: detail,
    });
  });

  it('states the name bound itself on a 422, whose detail is a list, not a sentence', () => {
    const error = cameraError(
      httpError(422, [{ loc: ['body', 'name'], msg: 'String should have at least 1 character' }]),
      FALLBACK,
    );

    expect(error.kind).toBe('invalid');
    expect(error.message).toContain('60 characters');
  });

  it('falls back only when nothing usable came back at all', () => {
    expect(cameraError({ status: 'FETCH_ERROR', error: 'boom' }, FALLBACK)).toEqual({
      kind: 'unknown',
      message: FALLBACK,
    });
    expect(cameraError(undefined, FALLBACK)).toEqual({ kind: 'unknown', message: FALLBACK });
  });

  it('still prefers the server’s sentence on an unrecognised status', () => {
    expect(cameraError(httpError(500, 'The saved position store is unreadable.'), FALLBACK)).toEqual(
      { kind: 'unknown', message: 'The saved position store is unreadable.' },
    );
  });

  it('states its own sentence when a refusal carries no detail', () => {
    expect(cameraError({ status: 501, data: {} }, FALLBACK).message).toContain(
      'cannot control the simulator camera',
    );
    expect(cameraError({ status: 409, data: {} }, FALLBACK).message).toContain(
      'drone/free camera',
    );
    expect(cameraError({ status: 404, data: {} }, FALLBACK).message).toContain(
      'no longer exists',
    );
  });
});
