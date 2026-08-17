/**
 * Client state for the Landing Analysis panel — and nothing else.
 *
 * The recorded landings are server state (RTK Query, `landingApi.ts`). All the panel
 * itself owns is which landing the instructor is debriefing.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { LandingId } from './types.mock';

export interface LandingUiState {
  /** The landing being debriefed; `null` until the instructor picks one. */
  selectedId: LandingId | null;
}

export const initialLandingUiState: LandingUiState = { selectedId: null };

const landingSlice = createSlice({
  name: 'landing',
  initialState: initialLandingUiState,
  reducers: {
    landingSelected(state, action: PayloadAction<LandingId>) {
      state.selectedId = action.payload;
    },
  },
});

export const { landingSelected } = landingSlice.actions;

export default landingSlice.reducer;
