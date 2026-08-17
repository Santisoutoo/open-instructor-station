/**
 * The one gate the Failures panel opens on, and it **fails closed** — the
 * `position/gate.ts` pattern verbatim (design §7.1).
 *
 * Hard rule 3: unsupported features are disabled in the UI, never left to throw at
 * runtime. That is only true if "I could not find out" counts as unsupported, so
 * capabilities that are still loading or failed to load disable everything exactly like
 * `can_inject_failures: false` does.
 *
 * This is the *tab-level* gate only. Row-level support (`supported`/`reason` per
 * catalogue entry, capability-free per §2.1) is read straight off `/catalogue` by
 * `FailureRow` — nothing here recomputes it.
 */

import type { Capabilities } from '../../api/models';

export interface FailuresGate {
  readonly open: boolean;
  /** Empty when open. Shown to the instructor verbatim. */
  readonly reason: string;
}

const OPEN: FailuresGate = { open: true, reason: '' };

export function failuresGate(
  capabilities: Capabilities | undefined,
  isError: boolean,
): FailuresGate {
  if (capabilities === undefined) {
    return {
      open: false,
      reason: isError
        ? 'The adapter capabilities could not be read, so failure injection is disabled.'
        : 'Waiting for the adapter capabilities…',
    };
  }
  if (!capabilities.can_inject_failures) {
    return {
      open: false,
      reason:
        'This adapter does not declare can_inject_failures, so failure injection is disabled.',
    };
  }
  return OPEN;
}
