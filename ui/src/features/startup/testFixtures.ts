/**
 * The bypass fixture every other manager's test needs to render `<App>` without going
 * through the gate — the `features/position/testFixtures.ts` precedent, one slice earlier
 * in the render tree than any of those.
 *
 * Named without `.test.` so Vitest does not try to run it as a suite.
 */

import type { StartupState } from './startupSlice';

/** A startup slice already past the gate, for tests that only care about what is behind it. */
export function readyStartupState(icao: string, name: string): StartupState {
  return { status: 'ready', query: icao, icao, name, errorMessage: null };
}
