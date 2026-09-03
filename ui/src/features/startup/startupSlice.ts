/**
 * The startup airport-selection gate's own state machine.
 *
 * Client intent only — no server data is duplicated into it. `startup.icao`/`startup.name`
 * exist only to drive the gate itself and the localStorage payload (`startupSync.ts`); the
 * instant `resolveSucceeded` fires, the resolve handler in `AirportGate.tsx` also dispatches
 * `positionSlice.airportSelected` and `positionDesignSlice.airportLoaded`, and from that point
 * on `positionDesign.loadedIcao` is the single place "which airport is loaded" lives for the
 * rest of the session. Nothing downstream of the gate ever reads `state.startup` again —
 * `AirportGate` itself unmounts once `status === 'ready'`.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

export type StartupStatus = 'idle' | 'searching' | 'resolving' | 'ready' | 'error';

/**
 * Below this, a query matches too much to be worth asking about — the same threshold
 * `AirportMenu.tsx` uses, duplicated rather than imported (the gate is a sibling
 * implementation, not a reuse of the Position manager's header menu).
 */
export const MIN_QUERY_LENGTH = 2;

export interface StartupState {
  status: StartupStatus;
  /** The combobox's raw text, updated on every keystroke. */
  query: string;
  /** The ICAO under resolution, or the last one resolved. `null` before the first attempt. */
  icao: string | null;
  /** The resolved (or remembered) airport's display name. `null` until known. */
  name: string | null;
  /** Set only in `error`; cleared by any further `queryTyped` or a new `resolveRequested`. */
  errorMessage: string | null;
}

export const initialStartupState: StartupState = {
  status: 'idle',
  query: '',
  icao: null,
  name: null,
  errorMessage: null,
};

const startupSlice = createSlice({
  name: 'startup',
  initialState: initialStartupState,
  reducers: {
    /** Every keystroke. Status follows the raw text's length; the debounce that gates the
     * actual network call is local component state, not stored here. */
    queryTyped(state, action: PayloadAction<string>) {
      state.query = action.payload;
      state.errorMessage = null;
      state.status = action.payload.trim().length >= MIN_QUERY_LENGTH ? 'searching' : 'idle';
    },

    /** Enter, or a suggestion click. Reachable from idle/searching/error — never from
     * resolving (the input is disabled there) or ready (the gate is gone). */
    resolveRequested(state, action: PayloadAction<string>) {
      state.status = 'resolving';
      state.icao = action.payload.toUpperCase();
      state.errorMessage = null;
    },

    /** The only transition into `ready`. */
    resolveSucceeded(state, action: PayloadAction<{ icao: string; name: string }>) {
      state.status = 'ready';
      state.icao = action.payload.icao;
      state.name = action.payload.name;
      state.errorMessage = null;
    },

    resolveFailed(state, action: PayloadAction<string>) {
      state.status = 'error';
      state.errorMessage = action.payload;
    },

    /** Boot-time prefill from localStorage. Pre-fills only — never resolves on its own, so
     * the gate always shows regardless of what is remembered. An ICAO is always
     * >= MIN_QUERY_LENGTH characters, so this always lands in `searching`. */
    rememberedAirportLoaded(state, action: PayloadAction<{ icao: string; name: string | null }>) {
      state.query = action.payload.icao;
      state.name = action.payload.name;
      state.status = action.payload.icao.length >= MIN_QUERY_LENGTH ? 'searching' : 'idle';
    },
  },
});

export const {
  queryTyped,
  resolveRequested,
  resolveSucceeded,
  resolveFailed,
  rememberedAirportLoaded,
} = startupSlice.actions;

export default startupSlice.reducer;
