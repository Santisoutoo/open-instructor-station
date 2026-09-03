/**
 * Client state for the Cockpit panel — and nothing else (design §7.2).
 *
 * The catalog and the state snapshot are server state (RTK Query, `cockpitApi.ts`,
 * polled/invalidated). What is here is only what the server cannot know: which panel is
 * selected, the search text, which controls have a write in flight, and the last write
 * failure. `pending` is a **lock**, not a value — a control's actual value always comes
 * from the confirmed snapshot (D8: never show the optimistic click as confirmed).
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import { telemetryCleared } from '../telemetry/telemetrySlice';

export interface CockpitUiState {
  /** `null` means "the first panel by order" — resolved by the component. */
  selectedPanelId: string | null;
  /** Non-empty flattens the panel picker into cross-panel search results. */
  search: string;
  /** Control ids with a write in flight. The widget locks while its id is a key here. */
  pending: Record<string, true>;
  /** The last 409/422/502 detail, shown once at the top of the panel. */
  lastError: string | null;
}

export const initialCockpitUiState: CockpitUiState = {
  selectedPanelId: null,
  search: '',
  pending: {},
  lastError: null,
};

const cockpitSlice = createSlice({
  name: 'cockpit',
  initialState: initialCockpitUiState,
  reducers: {
    /** Tap on the panel picker. */
    panelSelected(state, action: PayloadAction<string>) {
      state.selectedPanelId = action.payload;
    },
    /** Edit of the search field. */
    searchChanged(state, action: PayloadAction<string>) {
      state.search = action.payload;
    },
    /** A write left for the server. Locks the widget until it resolves either way. */
    actuationStarted(state, action: PayloadAction<string>) {
      state.pending[action.payload] = true;
      state.lastError = null;
    },
    /**
     * The write settled — success or failure, both unlock. `error` is set only on
     * failure; a success clears any previous error so a stale banner never lingers next
     * to a control that just worked.
     */
    actuationSettled(state, action: PayloadAction<{ controlId: string; error?: string }>) {
      delete state.pending[action.payload.controlId];
      state.lastError = action.payload.error ?? null;
    },
    /** Dismiss the error banner without touching any control. */
    errorDismissed(state) {
      state.lastError = null;
    },
  },
  extraReducers: (builder) => {
    // The `aircraftSlice` precedent: a lost link makes every belief stale, including
    // which writes were still in flight.
    builder.addCase(telemetryCleared, () => initialCockpitUiState);
  },
});

export const {
  panelSelected,
  searchChanged,
  actuationStarted,
  actuationSettled,
  errorDismissed,
} = cockpitSlice.actions;

export default cockpitSlice.reducer;

/** True while a write for `controlId` is in flight. */
export function selectIsPending(state: CockpitUiState, controlId: string): boolean {
  return state.pending[controlId] === true;
}
