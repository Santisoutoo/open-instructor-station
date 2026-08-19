/**
 * The one gate the Pushback panel opens on, and it **fails closed** — the
 * `position/gate.ts` pattern verbatim (design §7.3).
 *
 * Hard rule 3: unsupported features are disabled in the UI, never left to throw at
 * runtime. That is only true if "I could not find out" counts as unsupported, so
 * capabilities that are still loading or failed to load disable everything exactly
 * like `can_pushback: false` does.
 *
 * This is the *tab-level* gate and the only one this manager has: there is no
 * per-entry manifest to gate against (unlike Failures/Camera) — the
 * `distance_m`/`angle_deg` bounds are UI validation, not a capability question.
 */

import type { Capabilities } from '../../api/models';

export interface PushbackGate {
  readonly open: boolean;
  /** Empty when open. Shown to the instructor verbatim. */
  readonly reason: string;
}

const OPEN: PushbackGate = { open: true, reason: '' };

export function pushbackGate(
  capabilities: Capabilities | undefined,
  isError: boolean,
): PushbackGate {
  if (capabilities === undefined) {
    return {
      open: false,
      reason: isError
        ? 'The adapter capabilities could not be read, so pushback is disabled.'
        : 'Waiting for the adapter capabilities…',
    };
  }
  if (!capabilities.can_pushback) {
    return {
      open: false,
      reason: 'This adapter does not declare can_pushback, so pushback is disabled.',
    };
  }
  return OPEN;
}
