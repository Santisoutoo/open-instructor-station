/**
 * Client state of the Weather panel — and nothing else.
 *
 * The current weather is **server state** and lives in RTK Query (`weatherApi.ts`).
 * What is here is only what the server cannot know: which preset the instructor
 * staged and the edits they made on top of it. Staging moves no air — only the
 * apply mutation does.
 *
 * Overrides are kept sparse, like `positionSlice.setupOverrides`: an untouched
 * field must keep the preset's value, so this is an overlay and never a full copy
 * of the resolved state.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import { airportSelected } from '../position/positionSlice';
import type { WeatherOverrides, WeatherPresetId } from './types.mock';

export interface WeatherUiState {
  /** The staged preset, or `null` when nothing is staged. */
  selectedPresetId: WeatherPresetId | null;
  /** The instructor's edits on top of the staged preset. Sparse. */
  overrides: WeatherOverrides;
  /** True while something is staged — the editors and the staging bar render on it. */
  staged: boolean;
}

export const initialWeatherUiState: WeatherUiState = {
  selectedPresetId: null,
  overrides: {},
  staged: false,
};

const weatherSlice = createSlice({
  name: 'weather',
  initialState: initialWeatherUiState,
  reducers: {
    /** Stage a preset. Always clears previous edits: they belonged to another preset. */
    presetStaged(state, action: PayloadAction<WeatherPresetId>) {
      state.selectedPresetId = action.payload;
      state.overrides = {};
      state.staged = true;
    },
    /** One field of the staged weather changed. `null` removes the override. */
    overrideSet(
      state,
      action: PayloadAction<{ field: keyof WeatherOverrides; value: unknown }>,
    ) {
      const { field, value } = action.payload;
      if (value === null || value === undefined) {
        delete state.overrides[field];
      } else {
        Object.assign(state.overrides, { [field]: value });
      }
    },
    /** Applied, or dismissed: either way the staging surface goes away whole. */
    stagingCleared() {
      return initialWeatherUiState;
    },
  },
  extraReducers: (builder) => {
    // A staged preset is meaningless at another field — a crosswind resolved
    // against one runway must not survive into the next airport (accepted
    // direction of import: reacting to position's action, never the reverse).
    builder.addCase(airportSelected, () => initialWeatherUiState);
  },
});

export const { presetStaged, overrideSet, stagingCleared } = weatherSlice.actions;

export default weatherSlice.reducer;
