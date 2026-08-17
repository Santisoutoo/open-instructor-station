/**
 * The one gate the Traffic panel opens on, and it **fails closed** — the same pattern
 * as `features/position/gate.ts`.
 *
 * Hard rule 3: unsupported features are disabled in the UI, never left to throw at
 * runtime. That is only true if "I could not find out" counts as unsupported, so a
 * manifest that is still loading or failed to load disables everything exactly like
 * `available: false` does. Traffic is the strictest case of the rule: the whole manager
 * sits behind the bridge plugin (feature-spec §13), so there is no partial opening —
 * one gate for the entire panel.
 */

import type { TrafficManifest } from './types.mock';

export interface TrafficGate {
  readonly open: boolean;
  /** Empty when open. Shown to the instructor verbatim. */
  readonly reason: string;
}

const OPEN: TrafficGate = { open: true, reason: '' };

export function trafficGate(
  manifest: TrafficManifest | undefined,
  isError: boolean,
): TrafficGate {
  if (manifest === undefined) {
    return {
      open: false,
      reason: isError
        ? 'The traffic bridge status could not be read, so spawning is disabled.'
        : 'Waiting for the traffic bridge status…',
    };
  }
  if (!manifest.available) {
    return {
      open: false,
      reason:
        manifest.reason ??
        'This adapter does not declare can_spawn_traffic, so AI traffic is disabled.',
    };
  }
  return OPEN;
}
