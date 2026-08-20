/**
 * Client state for the Camera panel — and nothing else.
 *
 * The manifest and the saved-positions list are server state (RTK Query,
 * `cameraApi.ts`, wired once the camera server track lands). What is here is only what
 * the server cannot know — and, per design D6, one thing the server deliberately does
 * NOT know: which view is current. There is no honest read of the simulator's view, so
 * the panel highlights the last view it *requested* — optimistic, client-only, never
 * reconciled against a server read.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import { type CameraViewId } from '../../api/models';

export interface CameraUiState {
  /** The last view REQUESTED — the optimistic highlight (design D6), or `null` before the first tap. */
  lastRequestedView: CameraViewId | null;
  /** The saved position last applied, or `null`. Display-only. */
  selectedPositionId: string | null;
  /** The inline save form's name draft (design §7.2, client-only form state). */
  saveDraftName: string;
}

export const initialCameraUiState: CameraUiState = {
  lastRequestedView: null,
  selectedPositionId: null,
  saveDraftName: '',
};

const cameraSlice = createSlice({
  name: 'camera',
  initialState: initialCameraUiState,
  reducers: {
    /**
     * A view card was tapped. Switching to a named view also drops any recalled saved
     * position — the view alone does not imply one (design §4.1's Fake semantics).
     */
    viewRequested(state, action: PayloadAction<CameraViewId>) {
      state.lastRequestedView = action.payload;
      state.selectedPositionId = null;
    },
    /**
     * Apply was tapped on a saved position: recalling one puts the simulator in the
     * free camera, so the highlight moves to `drone` (the §11 walkthrough pins this).
     */
    positionApplied(state, action: PayloadAction<string>) {
      state.selectedPositionId = action.payload;
      state.lastRequestedView = 'drone';
    },
    /** A saved position was deleted; forget the selection only if it was that one. */
    positionDeleted(state, action: PayloadAction<string>) {
      if (state.selectedPositionId === action.payload) {
        state.selectedPositionId = null;
      }
    },
    saveDraftNameChanged(state, action: PayloadAction<string>) {
      state.saveDraftName = action.payload;
    },
    /** The save settled or was abandoned — either way the form resets. */
    saveDraftCleared(state) {
      state.saveDraftName = '';
    },
  },
});

export const {
  viewRequested,
  positionApplied,
  positionDeleted,
  saveDraftNameChanged,
  saveDraftCleared,
} = cameraSlice.actions;

export default cameraSlice.reducer;
