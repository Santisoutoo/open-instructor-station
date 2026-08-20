/**
 * Turning a refused pushback into a sentence an instructor can act on — and, above all,
 * keeping the server's **two different refusals apart**.
 *
 * `server/pushback_routes.py` is deliberate about this and the panel must not flatten it:
 *
 * - **501** — the adapter does not declare `can_pushback`. A *capability* answer: this
 *   simulator has no pushback at all, the panel should already have been disabled, and
 *   nothing the instructor does in the next minute will change it.
 * - **409** — `PushbackNotOnGround`. A *precondition*, not a capability: the adapter can
 *   push back perfectly well, but this aircraft is airborne right now. It clears the
 *   moment the wheels are down, so the controls stay live and only the commit is held
 *   back. Reading this as "unsupported" would disable the panel forever over a condition
 *   that is temporary by definition.
 *
 * The server always states a reason, so the job here is to *find* it rather than to
 * invent one; the fallbacks only cover the case where nothing came back at all.
 */

/** Which of the server's refusals this is — the whole point of the module. */
export type PushbackRefusalKind = 'unsupported' | 'not-on-ground' | 'unknown';

export interface PushbackRefusal {
  readonly kind: PushbackRefusalKind;
  /** The server's own sentence when it sent one. Shown verbatim. */
  readonly message: string;
}

/** Mirrors `server.pushback_routes.CAPABILITY_UNAVAILABLE_STATUS`. */
const CAPABILITY_UNAVAILABLE_STATUS = 501;

/** Mirrors `server.pushback_routes.NOT_ON_GROUND_STATUS`. */
const NOT_ON_GROUND_STATUS = 409;

/** The HTTP status RTK Query attached, or `null` for a transport-level failure. */
function statusOf(error: unknown): number | null {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const status = (error as { status: unknown }).status;
    if (typeof status === 'number') {
      return status;
    }
  }
  return null;
}

/** The `detail` string from a FastAPI error body, or `null` when there is none. */
function detailOf(error: unknown): string | null {
  if (typeof error === 'object' && error !== null && 'data' in error) {
    const data = (error as { data: unknown }).data;
    if (typeof data === 'object' && data !== null && 'detail' in data) {
      const detail = (data as { detail: unknown }).detail;
      if (typeof detail === 'string') {
        return detail;
      }
    }
  }
  return null;
}

export function describePushbackRefusal(error: unknown): PushbackRefusal {
  const detail = detailOf(error);
  switch (statusOf(error)) {
    case CAPABILITY_UNAVAILABLE_STATUS:
      return {
        kind: 'unsupported',
        message: detail ?? 'This adapter cannot push the aircraft back.',
      };
    case NOT_ON_GROUND_STATUS:
      return {
        kind: 'not-on-ground',
        message: detail ?? 'Cannot push back — the aircraft is airborne.',
      };
    default:
      return {
        kind: 'unknown',
        message: detail ?? 'The instructor server did not answer the pushback request.',
      };
  }
}

/**
 * Whether this refusal should take the controls away.
 *
 * **Only `unsupported` does.** An airborne aircraft clears on touchdown, and a dropped
 * connection clears when it comes back — disabling the panel for either would strand the
 * instructor with no way out but a reload. A single predicate rather than a flag on the
 * refusal, so "the copy says it is temporary" and "the panel stays usable" can never
 * drift apart.
 */
export function disablesPushback(refusal: PushbackRefusal | null): boolean {
  return refusal?.kind === 'unsupported';
}
