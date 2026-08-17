/**
 * Client state for the Failures panel — and nothing else.
 *
 * The catalogue and the armed/active board are server state (RTK Query,
 * `failuresApi.ts`). What is here is only what the server cannot know: the search
 * text, which accordion group is open, and the arm draft being edited inline.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import { defaultTrigger } from './triggers';
import type { FailureSystem, FailureTrigger, TriggerType } from './types.mock';

/** The row currently expanded into the trigger editor, and the trigger it is editing. */
export interface ArmDraft {
  failureId: string;
  trigger: FailureTrigger;
}

export interface FailuresUiState {
  /** Filters the catalogue across every group; empty shows the accordion as usual. */
  searchText: string;
  /** The one open accordion group, or `null` when all are collapsed. */
  openSystem: FailureSystem | null;
  /** The inline editor's state, or `null` when no row is expanded. */
  armDraft: ArmDraft | null;
}

export const initialFailuresUiState: FailuresUiState = {
  searchText: '',
  openSystem: 'engine',
  armDraft: null,
};

const failuresSlice = createSlice({
  name: 'failures',
  initialState: initialFailuresUiState,
  reducers: {
    searchChanged(state, action: PayloadAction<string>) {
      state.searchText = action.payload;
    },
    /** Tap on a group header: open it, or close it if it was the open one. */
    systemToggled(state, action: PayloadAction<FailureSystem>) {
      state.openSystem = state.openSystem === action.payload ? null : action.payload;
    },
    /** "Arm…" on a row: expand it with the default trigger. Replaces any other draft. */
    armDraftOpened(state, action: PayloadAction<string>) {
      state.armDraft = { failureId: action.payload, trigger: defaultTrigger('altitude') };
    },
    /** Switching trigger type resets the draft to that type's default values. */
    armDraftTypeChanged(state, action: PayloadAction<TriggerType>) {
      if (state.armDraft !== null) {
        state.armDraft.trigger = defaultTrigger(action.payload);
      }
    },
    /** An edit inside the editor: the whole trigger is replaced, keeping it one shape. */
    armDraftTriggerChanged(state, action: PayloadAction<FailureTrigger>) {
      if (state.armDraft !== null) {
        state.armDraft.trigger = action.payload;
      }
    },
    /** Cancel, or the arm mutation settled — either way the row collapses. */
    armDraftClosed(state) {
      state.armDraft = null;
    },
  },
});

export const {
  searchChanged,
  systemToggled,
  armDraftOpened,
  armDraftTypeChanged,
  armDraftTriggerChanged,
  armDraftClosed,
} = failuresSlice.actions;

export default failuresSlice.reducer;
