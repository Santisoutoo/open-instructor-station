/**
 * Client state for the Scenarios panel — and nothing else.
 *
 * The catalogue itself is server state (RTK Query, `scenariosApi.ts`). What is here is
 * only what the server cannot know: which card the instructor tapped, and the run that
 * is currently playing out. The run is a *visual* progression — a checklist ticking as
 * the mock engine advances — and never dispatches into other features.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

export interface ScenarioRunStep {
  label: string;
  done: boolean;
}

export interface ScenarioRunState {
  id: string;
  name: string;
  /** Epoch ms; the elapsed timer is derived from it, never stored. */
  startedAt: number;
  steps: ScenarioRunStep[];
  stopped: boolean;
}

export interface ScenariosUiState {
  /** The card the instructor tapped once; its Run button is showing. */
  selectedId: string | null;
  /** The run in progress, or `null` when the panel shows only the catalogue. */
  runState: ScenarioRunState | null;
}

export const initialScenariosUiState: ScenariosUiState = {
  selectedId: null,
  runState: null,
};

const scenariosSlice = createSlice({
  name: 'scenarios',
  initialState: initialScenariosUiState,
  reducers: {
    /** First tap on a card. `null` clears the selection. */
    scenarioSelected(state, action: PayloadAction<string | null>) {
      state.selectedId = action.payload;
    },
    /**
     * Second tap — start the run. `startedAt` is stamped in `prepare` so the reducer
     * stays pure and time-travel replays keep the original start time.
     */
    runStarted: {
      prepare(input: { id: string; name: string; steps: string[] }) {
        return { payload: { ...input, startedAt: Date.now() } };
      },
      reducer(
        state,
        action: PayloadAction<{
          id: string;
          name: string;
          steps: string[];
          startedAt: number;
        }>,
      ) {
        state.runState = {
          id: action.payload.id,
          name: action.payload.name,
          startedAt: action.payload.startedAt,
          steps: action.payload.steps.map((label) => ({ label, done: false })),
          stopped: false,
        };
      },
    },
    /** The mock engine ticked: mark the next pending step done, strictly in order. */
    runStepCompleted(state) {
      const next = state.runState?.steps.find((step) => !step.done);
      if (next !== undefined) {
        next.done = true;
      }
    },
    runStopped(state) {
      if (state.runState !== null) {
        state.runState.stopped = true;
      }
    },
    runCleared(state) {
      state.runState = null;
    },
  },
});

export const { scenarioSelected, runStarted, runStepCompleted, runStopped, runCleared } =
  scenariosSlice.actions;

/**
 * Plain selector over the slice's slot in the root state. Typed structurally so the
 * shell's status bar (or any consumer) can use it without importing `RootState`.
 */
export function selectScenarioRun(state: {
  scenarios: ScenariosUiState;
}): ScenarioRunState | null {
  return state.scenarios.runState;
}

export default scenariosSlice.reducer;
