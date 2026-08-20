/**
 * Turning an RTK Query error into a sentence an instructor can act on — and, before
 * that, into the *kind* of thing that went wrong.
 *
 * The Camera Manager has four failures that must not be conflated, because the action
 * they ask of the instructor is different in each case (design §2.1/§2.2):
 *
 * | HTTP | kind | What it means | What to do about it |
 * |---|---|---|---|
 * | 501 | `unsupported` | This adapter cannot do it — no `can_control_camera`, an unsupported view, or no free-camera positioning. | Nothing. It will not work on this install. |
 * | 409 | `precondition` | Nothing is wrong with the adapter; there is just no live free-camera pose to capture right now (D9). | Switch to the drone camera and try again. |
 * | 404 | `missing` | The saved id is gone — deleted in another tab, or the store was cleared. | Nothing; the list refreshes itself. |
 * | 422 | `invalid` | The name is empty or over 60 characters. | Fix the name. |
 *
 * Collapsing 409 into "unsupported" would tell an instructor to give up on something
 * that works — which is why the kind travels with the message rather than the panel
 * inferring it from the wording.
 *
 * The server states a reason for the first three, so the job here is to *find* it rather
 * than invent one. 422 is the exception: FastAPI's validation `detail` is a list of
 * error objects, not a sentence, so this is the one case with wording of its own — and
 * it mirrors `SaveCameraPositionRequest`'s own bound.
 *
 * A near-relative of `features/scenarios/errors.ts` rather than a shared import: each
 * manager owns its own small logic (CLAUDE.md — adding a manager must not require
 * touching the others).
 */

export type CameraErrorKind =
  | 'unsupported'
  | 'precondition'
  | 'missing'
  | 'invalid'
  | 'unknown';

export interface CameraError {
  readonly kind: CameraErrorKind;
  /** Shown to the instructor verbatim. */
  readonly message: string;
}

/** The `name` bound `SaveCameraPositionRequest` declares, restated for the 422 body. */
const INVALID_NAME =
  'A position name must be between 1 and 60 characters. Rename it and save again.';

function statusOf(error: unknown): number | null {
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const status = (error as { status: unknown }).status;
    return typeof status === 'number' ? status : null;
  }
  return null;
}

/** The `detail` string of a FastAPI error body, when there is one. */
function detailOf(error: unknown): string | null {
  if (typeof error === 'object' && error !== null && 'data' in error) {
    const data = (error as { data: unknown }).data;
    if (typeof data === 'object' && data !== null && 'detail' in data) {
      const detail = (data as { detail: unknown }).detail;
      if (typeof detail === 'string' && detail !== '') {
        return detail;
      }
    }
  }
  return null;
}

/**
 * Classify one failed request. `fallback` covers only the case where nothing usable came
 * back at all — a dropped connection, not a refusal.
 */
export function cameraError(error: unknown, fallback: string): CameraError {
  const detail = detailOf(error);
  switch (statusOf(error)) {
    case 501:
      return {
        kind: 'unsupported',
        message: detail ?? 'This adapter cannot control the simulator camera.',
      };
    case 409:
      return {
        kind: 'precondition',
        message:
          detail ??
          'Cannot save a camera position right now — switch to the drone/free camera first.',
      };
    case 404:
      return {
        kind: 'missing',
        message: detail ?? 'That saved camera position no longer exists.',
      };
    case 422:
      return { kind: 'invalid', message: INVALID_NAME };
    default:
      return { kind: 'unknown', message: detail ?? fallback };
  }
}
