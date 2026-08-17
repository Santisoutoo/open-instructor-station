/**
 * The gates the Weather panel opens on, and both **fail closed** — the same pattern
 * as `features/position/gate.ts` and `features/traffic/gate.ts`.
 *
 * Hard rule 3: unsupported features are disabled in the UI, never left to throw at
 * runtime — and "I could not find out" counts as unsupported. Staging an override on
 * top of a baseline the panel has not read would show the instructor values that are
 * not true, so an unread current weather disables the whole staging surface.
 */

// MOCK: also gate on Capabilities.can_set_weather at backend integration — the
// capability flag is what MSFS will declare false (feature-spec §3).

import type { WeatherPreset, WeatherState } from './types.mock';

export interface WeatherGate {
  readonly open: boolean;
  /** Empty when open. Shown to the instructor verbatim. */
  readonly reason: string;
}

const OPEN: WeatherGate = { open: true, reason: '' };

/** May the panel stage and apply at all? Closed until the current weather is known. */
export function weatherGate(
  state: WeatherState | undefined,
  isError: boolean,
): WeatherGate {
  if (state === undefined) {
    return {
      open: false,
      reason: isError
        ? 'The current weather could not be read, so setting weather is disabled.'
        : 'Reading the current weather…',
    };
  }
  return OPEN;
}

/**
 * May this preset be staged? Relative presets need a runway to resolve against,
 * so their tile stays disabled — with the reason on the tile, never a tooltip —
 * until the Position panel has an airport and runway selected.
 */
export function presetGate(
  preset: WeatherPreset,
  selectedIcao: string | null,
  selectedRunwayIdent: string | null,
): WeatherGate {
  if (!preset.requires_runway) {
    return OPEN;
  }
  if (selectedIcao === null || selectedRunwayIdent === null) {
    return {
      open: false,
      reason: 'Relative to a runway — select an airport and runway in Position first.',
    };
  }
  return OPEN;
}
