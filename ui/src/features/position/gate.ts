/**
 * The two gates the Position panel opens on, and both **fail closed**.
 *
 * Hard rule 3 says unsupported features are disabled in the UI, never left to throw at
 * runtime. That is only true if "I could not find out" counts as unsupported — otherwise a
 * server that is merely slow or unreachable reads as fully capable, and the panel offers a
 * button that cannot work. So an absent answer disables, exactly as
 * `features/aircraft/controls.ts` already does for the control manifest.
 *
 * The two gates are genuinely different questions and are kept apart:
 *
 * - **Capabilities** asks whether the simulator can be moved. When it says no, staging
 *   still works — a preview is navdata and arithmetic — and only the commit button dies.
 * - **Navdata** asks whether there is a world to place *in*. When it says no, there is
 *   nothing to show at all, so the panel body is replaced by the status card.
 */

import type { Capabilities, NavdataStatus } from '../../api/models';

export interface Gate {
  readonly open: boolean;
  /** Empty when open. Shown to the instructor verbatim. */
  readonly reason: string;
}

const OPEN: Gate = { open: true, reason: '' };

/**
 * May this adapter be commanded to reposition the aircraft?
 *
 * Only gates the **commit**. Preview needs no simulator at all.
 */
export function commitGate(
  capabilities: Capabilities | undefined,
  isError: boolean,
): Gate {
  if (capabilities === undefined) {
    return {
      open: false,
      reason: isError
        ? 'The adapter capabilities could not be read, so placing is disabled.'
        : 'Waiting for the adapter capabilities…',
    };
  }
  if (!capabilities.can_set_position) {
    return {
      open: false,
      reason:
        'This adapter does not declare can_set_position, so it cannot be repositioned.',
    };
  }
  if (!capabilities.can_set_aircraft_state) {
    return {
      open: false,
      reason:
        'This adapter cannot set speed or altitude, which every placement needs written ' +
        'before the aircraft is moved.',
    };
  }
  return OPEN;
}

/** What the panel should render instead of itself, if anything. */
export type NavdataGate =
  | { readonly kind: 'ready' }
  | { readonly kind: 'loading'; readonly reason: string }
  | {
      readonly kind: 'building';
      readonly reason: string;
      readonly fraction: number | null;
    }
  | { readonly kind: 'blocked'; readonly reason: string; readonly canBuild: boolean };

/**
 * Resolve the navdata status into what to draw.
 *
 * `unavailable` offers a build button and `error` does not: an index that has never been
 * built is one click from working, while one that failed will fail again the same way
 * until the underlying problem — a missing install, an unreadable file — is fixed. Offering
 * a button that re-runs a known failure is worse than saying what went wrong.
 */
export function navdataGate(
  status: NavdataStatus | undefined,
  isError: boolean,
): NavdataGate {
  if (status === undefined) {
    return isError
      ? {
          kind: 'blocked',
          reason: 'The navigation data status could not be read.',
          canBuild: false,
        }
      : { kind: 'loading', reason: 'Reading the navigation data status…' };
  }

  switch (status.state) {
    case 'ready':
      return { kind: 'ready' };
    case 'building':
      return {
        kind: 'building',
        reason: status.progress?.detail ?? 'Building the navigation index…',
        fraction: status.progress?.fraction ?? null,
      };
    case 'unavailable':
      return {
        kind: 'blocked',
        reason: status.reason ?? 'No navigation data has been indexed yet.',
        canBuild: true,
      };
    case 'error':
      return {
        kind: 'blocked',
        reason: status.reason ?? 'The navigation index could not be read.',
        canBuild: false,
      };
  }
}

/** The AIRAC cycle to show beside the airport, or `null` when the provider has none. */
export function airacLabel(status: NavdataStatus | undefined): string | null {
  if (status?.airac_cycle == null) {
    return null;
  }
  return `AIRAC ${status.airac_cycle}`;
}
