/**
 * The one gate the Cockpit panel opens on, and it **fails closed** — the
 * `camera/gate.ts` / `failures/gate.ts` pattern verbatim (design §7.3).
 *
 * Hard rule 3: unsupported features are disabled in the UI, never left to throw at
 * runtime. That is only true if "I could not find out" counts as unsupported, so
 * capabilities that are still loading or failed to load disable everything exactly like
 * `can_control_cockpit: false` does.
 *
 * This is the *tab-level* gate only. Whether a catalog is active for the loaded aircraft
 * (`supported`/`aircraft`/`reason` on `CockpitCatalogManifest`, capability-free per D1) is
 * read straight off `GET /cockpit/catalog` by `CockpitPanel` — nothing here recomputes it.
 */

import type { Capabilities } from '../../api/models';

export interface CockpitGate {
  readonly open: boolean;
  /** Empty when open. Shown to the instructor verbatim. */
  readonly reason: string;
}

const OPEN: CockpitGate = { open: true, reason: '' };

export function cockpitGate(
  capabilities: Capabilities | undefined,
  isError: boolean,
): CockpitGate {
  if (capabilities === undefined) {
    return {
      open: false,
      reason: isError
        ? 'The adapter capabilities could not be read, so cockpit control is disabled.'
        : 'Waiting for the adapter capabilities…',
    };
  }
  if (!capabilities.can_control_cockpit) {
    return {
      open: false,
      reason:
        'This adapter does not declare can_control_cockpit, so cockpit control is disabled.',
    };
  }
  return OPEN;
}
