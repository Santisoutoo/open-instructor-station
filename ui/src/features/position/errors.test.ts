/**
 * The server always states a reason; this must find it rather than invent one.
 *
 * A 501 names the capability the adapter does not declare and a 422 carries the leg's own
 * `unpositionable_reason`. Swallowing those and showing a generic sentence would throw
 * away the only part of the message the instructor can act on.
 */

import { describe, expect, it } from 'vitest';
import { errorMessage } from './errors';

describe('errorMessage', () => {
  it("surfaces FastAPI's detail verbatim", () => {
    const error = {
      status: 422,
      data: { detail: 'A CA leg ends at an altitude, not at a fix.' },
    };

    expect(errorMessage(error, 'fallback')).toBe(
      'A CA leg ends at an altitude, not at a fix.',
    );
  });

  it('falls back when there is no body at all', () => {
    expect(errorMessage({ status: 'FETCH_ERROR' }, 'fallback')).toBe('fallback');
    expect(errorMessage(undefined, 'fallback')).toBe('fallback');
    expect(errorMessage(null, 'fallback')).toBe('fallback');
  });

  it('falls back when the detail is not a string', () => {
    // FastAPI's validation errors put a list of objects in `detail`; rendering that as
    // "[object Object]" would be worse than the fallback sentence.
    const error = { status: 422, data: { detail: [{ loc: ['body'], msg: 'bad' }] } };

    expect(errorMessage(error, 'fallback')).toBe('fallback');
  });
});
