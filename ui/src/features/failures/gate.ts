/**
 * The one gate the Failures panel opens on, and it **fails closed** — the same pattern
 * as `features/traffic/gate.ts`.
 *
 * Hard rule 3: unsupported features are disabled in the UI, never left to throw at
 * runtime. That is only true if "I could not find out" counts as unsupported, so a
 * manifest that is still loading or failed to load disables everything exactly like
 * `available: false` does.
 */

import type { FailuresManifest } from './types.mock';

export interface FailuresGate {
  readonly open: boolean;
  /** Empty when open. Shown to the instructor verbatim. */
  readonly reason: string;
}

const OPEN: FailuresGate = { open: true, reason: '' };

export function failuresGate(
  manifest: FailuresManifest | undefined,
  isError: boolean,
): FailuresGate {
  if (manifest === undefined) {
    return {
      open: false,
      reason: isError
        ? 'The failure injection status could not be read, so injection is disabled.'
        : 'Waiting for the failure injection status…',
    };
  }
  if (!manifest.available) {
    return {
      open: false,
      reason:
        manifest.reason ??
        'This adapter does not declare can_inject_failures, so injection is disabled.',
    };
  }
  return OPEN;
}
