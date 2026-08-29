/**
 * Client state for the Scenarios panel — and nothing else.
 *
 * The catalogue and a run's progress are both server state (RTK Query, `scenariosApi.ts`
 * — design §7.2: "unlike Weather/Failures there is no staging/editing surface here"). What
 * is here is only what the server cannot know: which card the instructor tapped, and
 * whether the most recently reported run's bar has been dismissed. Per-step progress is
 * never mirrored into this slice — `useGetScenarioRunQuery`'s cache is the single source
 * of truth for it (CLAUDE.md: RTK Query for server state).
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

export interface ScenariosUiState {
  /** The card the instructor tapped once; its Run button is showing. */
  selectedId: string | null;
  /**
   * `"<scenario_id>:<started_at>"` of the last run dismissed from the active bar. A run
   * whose key does not match this is shown. Dismissing never reaches the server — there
   * is no cancel/abort endpoint (design §10.6); it only stops the bar rendering client-side
   * while the run itself keeps going.
   */
  dismissedRunKey: string | null;
}

export const initialScenariosUiState: ScenariosUiState = {
  selectedId: null,
  dismissedRunKey: null,
};

const scenariosSlice = createSlice({
  name: 'scenarios',
  initialState: initialScenariosUiState,
  reducers: {
    /** First tap on a card. `null` clears the selection. */
    scenarioSelected(state, action: PayloadAction<string | null>) {
      state.selectedId = action.payload;
    },
    /** Hide the active-run bar for one run, keyed by scenario id + start time. */
    runDismissed(state, action: PayloadAction<string>) {
      state.dismissedRunKey = action.payload;
    },
  },
});

export const { scenarioSelected, runDismissed } = scenariosSlice.actions;

export default scenariosSlice.reducer;
