/**
 * The startup gate's own boot hook: reads the remembered airport out of `localStorage` before
 * first render, and writes the resolved one back once the gate closes.
 *
 * A small copy of `store/uiSync.ts`'s `readStorage`/`writeStorage` try/catch, deliberately
 * duplicated rather than exported from `uiSync.ts` — that file's own scope is the hash
 * listener, the theme and the demo-feed preference, and pulling it outside that concern to
 * share two three-line helpers is not worth the coupling. Called once from `main.tsx`, next
 * to `initUiSync(store)`.
 */

import type { AppStore } from '../../store';
import { rememberedAirportLoaded } from './startupSlice';

export const STARTUP_AIRPORT_STORAGE_KEY = 'ois-startup-airport';

interface RememberedAirport {
  readonly icao: string;
  readonly name: string | null;
}

function isRememberedAirport(value: unknown): value is RememberedAirport {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.icao === 'string' &&
    (candidate.name === null || typeof candidate.name === 'string')
  );
}

function readStartupStorage(): RememberedAirport | null {
  try {
    const raw = localStorage.getItem(STARTUP_AIRPORT_STORAGE_KEY);
    if (raw === null) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    return isRememberedAirport(parsed) ? parsed : null;
  } catch {
    // Storage unavailable (private mode) or a corrupt payload — degrade to an empty gate,
    // never a crash.
    return null;
  }
}

function writeStartupStorage(airport: RememberedAirport): void {
  try {
    localStorage.setItem(STARTUP_AIRPORT_STORAGE_KEY, JSON.stringify(airport));
  } catch {
    /* storage may be unavailable (private mode); the app still works, unpersisted */
  }
}

export function initStartupSync(store: AppStore): void {
  const remembered = readStartupStorage();
  if (remembered !== null) {
    store.dispatch(rememberedAirportLoaded(remembered));
  }

  let last = store.getState().startup.status;
  store.subscribe(() => {
    const next = store.getState().startup;
    if (next.status === 'ready' && last !== 'ready' && next.icao !== null) {
      writeStartupStorage({ icao: next.icao, name: next.name });
    }
    last = next.status;
  });
}
