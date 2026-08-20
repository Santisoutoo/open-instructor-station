/**
 * The one gate the Camera panel opens on, and it **fails closed** — the
 * `position/gate.ts` pattern verbatim (design §7.3).
 *
 * Hard rule 3: unsupported features are disabled in the UI, never left to throw at
 * runtime. That is only true if "I could not find out" counts as unsupported, so
 * capabilities that are still loading or failed to load disable everything exactly like
 * `can_control_camera: false` does.
 *
 * This is the *tab-level* gate only. View-level support (`supported`/`reason` per
 * catalogue entry) and the saved-positions tier (`custom_positions_supported`) are read
 * straight off `/manifest` by `ViewGrid`/`SavedPositions` — nothing here recomputes
 * them.
 */

import { type Capabilities } from '../../api/models';

export interface CameraGate {
  readonly open: boolean;
  /** Empty when open. Shown to the instructor verbatim. */
  readonly reason: string;
}

const OPEN: CameraGate = { open: true, reason: '' };

export function cameraGate(
  capabilities: Capabilities | undefined,
  isError: boolean,
): CameraGate {
  if (capabilities === undefined) {
    return {
      open: false,
      reason: isError
        ? 'The adapter capabilities could not be read, so camera control is disabled.'
        : 'Waiting for the adapter capabilities…',
    };
  }
  if (!capabilities.can_control_camera) {
    return {
      open: false,
      reason:
        'This adapter does not declare can_control_camera, so camera control is disabled.',
    };
  }
  return OPEN;
}
