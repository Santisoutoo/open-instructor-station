/**
 * The one gate the Traffic panel opens on, and it **fails closed** — the
 * `position/gate.ts` / `failures/gate.ts` pattern verbatim (design §7.1).
 *
 * Hard rule 3: unsupported features are disabled in the UI, never left to throw at
 * runtime. That is only true if "I could not find out" counts as unsupported, so
 * capabilities that are still loading or failed to load disable everything exactly like
 * `can_spawn_traffic: false` does. Traffic is the strictest case of the rule: the whole
 * manager sits behind the optional in-sim bridge plugin, so there is no partial opening
 * — one gate for the entire panel (design §7.3: no per-entry gating below it).
 */

import type { Capabilities } from '../../api/models';

export interface TrafficGate {
  readonly open: boolean;
  /** Empty when open. Shown to the instructor verbatim. */
  readonly reason: string;
}

const OPEN: TrafficGate = { open: true, reason: '' };

export function trafficGate(
  capabilities: Capabilities | undefined,
  isError: boolean,
): TrafficGate {
  if (capabilities === undefined) {
    return {
      open: false,
      reason: isError
        ? 'The adapter capabilities could not be read, so traffic spawning is disabled.'
        : 'Waiting for the adapter capabilities…',
    };
  }
  if (!capabilities.can_spawn_traffic) {
    return {
      open: false,
      reason:
        'This adapter does not declare can_spawn_traffic, so AI traffic is disabled. ' +
        'Traffic needs the in-sim bridge plugin; everything else works without it.',
    };
  }
  return OPEN;
}
