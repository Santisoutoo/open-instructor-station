/**
 * Client state for the Failures panel — and nothing else.
 *
 * The catalogue and the armed/active board are server state (RTK Query,
 * `failuresApi.ts`, polled). What is here is only what the server cannot know: the
 * search text, which accordion category is open, and the arm draft being edited inline.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import { defaultTrigger } from './triggers';
import type {
  FailureCategory,
  FailureId,
  FailureTrigger,
  FailureTriggerType,
} from '../../api/models';

/** The row currently expanded into the trigger editor, and the trigger it is editing. */
export interface ArmDraft {
  failureId: FailureId;
  /** `null` unless the catalogue entry `takes_engine_index`. Fixed at open time. */
  engineIndex: number | null;
  trigger: FailureTrigger;
}

export interface FailuresUiState {
  /** Filters the catalogue across every category; empty shows the accordion as usual. */
  searchText: string;
  /** The one open accordion category, or `null` when all are collapsed. */
  openCategory: FailureCategory | null;
  /** The inline editor's state, or `null` when no row is expanded. */
  armDraft: ArmDraft | null;
}

export const initialFailuresUiState: FailuresUiState = {
  searchText: '',
  openCategory: 'engine',
  armDraft: null,
};

const failuresSlice = createSlice({
  name: 'failures',
  initialState: initialFailuresUiState,
  reducers: {
    searchChanged(state, action: PayloadAction<string>) {
      state.searchText = action.payload;
    },
    /** Tap on a category header: open it, or close it if it was the open one. */
    categoryToggled(state, action: PayloadAction<FailureCategory>) {
      state.openCategory = state.openCategory === action.payload ? null : action.payload;
    },
    /** "Arm…" on a row: expand it with the default trigger. Replaces any other draft. */
    armDraftOpened(
      state,
      action: PayloadAction<{ failureId: FailureId; engineIndex: number | null }>,
    ) {
      state.armDraft = {
        failureId: action.payload.failureId,
        engineIndex: action.payload.engineIndex,
        trigger: defaultTrigger('altitude_above'),
      };
    },
    /** Switching trigger type resets the draft to that type's default values. */
    armDraftTypeChanged(state, action: PayloadAction<FailureTriggerType>) {
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
  categoryToggled,
  armDraftOpened,
  armDraftTypeChanged,
  armDraftTriggerChanged,
  armDraftClosed,
} = failuresSlice.actions;

export default failuresSlice.reducer;
