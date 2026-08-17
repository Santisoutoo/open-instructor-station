/**
 * The gate the Fuel & Payload panel opens on — fails **closed**, the same pattern as
 * `features/position/gate.ts`'s `commitGate` and `features/weather/gate.ts`'s
 * `weatherGate`.
 *
 * Hard rule 3: unsupported features are disabled in the UI, never left to throw at
 * runtime — and "I could not find out" counts as unsupported. The manifest carries
 * both the capability and its reason in one round trip (D14 of the design), so one
 * gate is enough here, unlike Position's separate capabilities/navdata split.
 */

import type { FuelPayloadManifest } from '../../api/models';

export interface FuelPayloadGate {
  readonly open: boolean;
  /** Empty when open. Shown to the instructor verbatim. */
  readonly reason: string;
}

const OPEN: FuelPayloadGate = { open: true, reason: '' };

export function fuelPayloadGate(
  manifest: FuelPayloadManifest | undefined,
  isError: boolean,
): FuelPayloadGate {
  if (manifest === undefined) {
    return {
      open: false,
      reason: isError
        ? 'The fuel & payload manifest could not be read, so the panel is disabled.'
        : 'Reading the fuel & payload manifest…',
    };
  }
  if (!manifest.supported) {
    return {
      open: false,
      reason: manifest.reason ?? 'This adapter does not support fuel and payload control.',
    };
  }
  return OPEN;
}
