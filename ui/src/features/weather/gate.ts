/**
 * The gates the Weather panel opens on, and both **fail closed** — the same pattern as
 * `features/position/gate.ts` and `features/traffic/gate.ts`.
 *
 * Hard rule 3: unsupported features are disabled in the UI, never left to throw at runtime —
 * and "I could not find out" counts as unsupported. `weatherGate` reads
 * `Capabilities.can_set_weather` the same way `CapabilityList.tsx` and
 * `features/position/gate.ts`'s `commitGate` already do, through `useGetCapabilitiesQuery`:
 * while the flag is `False` (the X-Plane adapter today, pending live verification) the whole
 * panel fails closed, because `GET /api/weather` itself 501s without it — there is no partial
 * "preview only" mode here the way Position has, since a weather preview cannot even show a
 * current-weather baseline to compose over.
 */

import type { Capabilities, WeatherPresetInfo, WeatherState } from '../../api/models';

export interface WeatherGate {
  readonly open: boolean;
  /** Empty when open. Shown to the instructor verbatim. */
  readonly reason: string;
}

const OPEN: WeatherGate = { open: true, reason: '' };

/**
 * May the panel stage and apply at all?
 *
 * Closed until the adapter declares `can_set_weather` and the current weather is known —
 * checked in that order, so an unsupported adapter reads as "unsupported", not as a generic
 * read failure.
 */
export function weatherGate(
  capabilities: Capabilities | undefined,
  capabilitiesFailed: boolean,
  state: WeatherState | undefined,
  stateFailed: boolean,
): WeatherGate {
  if (capabilities === undefined) {
    return {
      open: false,
      reason: capabilitiesFailed
        ? 'The adapter capabilities could not be read, so setting weather is disabled.'
        : 'Waiting for the adapter capabilities…',
    };
  }
  if (!capabilities.can_set_weather) {
    return {
      open: false,
      reason: 'This adapter does not declare can_set_weather, so weather cannot be set.',
    };
  }
  if (state === undefined) {
    return {
      open: false,
      reason: stateFailed
        ? 'The current weather could not be read, so setting weather is disabled.'
        : 'Reading the current weather…',
    };
  }
  return OPEN;
}

/**
 * May this preset be staged? A preset stating any wind or cloud layer needs a field's
 * elevation to resolve its AGL heights, and a preset whose wind is runway-relative needs
 * a runway on top of that — so its tile stays disabled, with the reason on the tile, never
 * a tooltip, until the Position panel has the airport (and, if needed, the runway) selected.
 */
export function presetGate(
  preset: WeatherPresetInfo,
  selectedIcao: string | null,
  selectedRunwayIdent: string | null,
): WeatherGate {
  if (preset.requires_runway && (selectedIcao === null || selectedRunwayIdent === null)) {
    return {
      open: false,
      reason: 'Relative to a runway — select an airport and runway in Position first.',
    };
  }
  if (preset.requires_airport && selectedIcao === null) {
    return {
      open: false,
      reason: 'States altitudes above the field — select an airport in Position first.',
    };
  }
  return OPEN;
}
