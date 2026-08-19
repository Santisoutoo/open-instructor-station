/**
 * The one gate the Pushback panel opens on, and it **fails closed**.
 *
 * Hard rule 3: unsupported features are disabled in the UI, never left to throw at
 * runtime. That is only true if "I could not find out" counts as unsupported, so a
 * manifest that is still loading or failed to load disables everything exactly like
 * `supported: false` does.
 *
 * It gates on `GET /api/pushback/manifest` rather than on `GET /api/capabilities`, which
 * is a deliberate narrowing of design §7.3: `manifest.supported` **is**
 * `capabilities.can_pushback` — the route reads that very flag — but the manifest also
 * carries the server's own sentence for why not, and the `max_distance_m`/`max_angle_deg`
 * bounds the sliders need. Gating on capabilities would mean reading one truth from two
 * endpoints and inventing copy the server has already written. This is the same argument
 * `instructorApi.ts` makes for preferring `getAircraftControls` to `getCapabilities`.
 *
 * This is the *tab-level* gate and the only one this manager has: there is no per-entry
 * manifest to gate against (unlike Failures/Camera). It is also **not** where "the
 * aircraft is airborne" belongs — that is a state precondition the server answers with a
 * 409 on every preview, and it is transient; see `errors.ts`.
 */

import type { PushbackManifest } from '../../api/models';

export interface PushbackGate {
  readonly open: boolean;
  /** Empty when open. Shown to the instructor verbatim. */
  readonly reason: string;
  /**
   * The bound the distance slider must respect, straight from the manifest — the reason
   * the panel needs no constant of its own. `undefined` exactly when the gate is closed,
   * which is exactly when there is no manifest to have read it from.
   */
  readonly maxDistanceM: number | undefined;
  /** The same, for the turn-angle slider. */
  readonly maxAngleDeg: number | undefined;
}

function closed(reason: string): PushbackGate {
  return { open: false, reason, maxDistanceM: undefined, maxAngleDeg: undefined };
}

export function pushbackGate(
  manifest: PushbackManifest | undefined,
  isError: boolean,
): PushbackGate {
  if (manifest === undefined) {
    return closed(
      isError
        ? 'The pushback manifest could not be read, so pushback is disabled.'
        : 'Waiting for the pushback manifest…',
    );
  }
  if (!manifest.supported) {
    return closed(
      manifest.reason ?? 'This adapter does not declare can_pushback, so pushback is disabled.',
    );
  }
  return {
    open: true,
    reason: '',
    maxDistanceM: manifest.max_distance_m,
    maxAngleDeg: manifest.max_angle_deg,
  };
}
