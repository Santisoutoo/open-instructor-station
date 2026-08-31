/**
 * Client state of the Weather panel — and nothing else.
 *
 * The current weather is **server state** and lives in RTK Query (`weatherApi.ts`). What is
 * here is only what the server cannot know: which preset the instructor staged and the edits
 * they made on top of it. Staging moves no air — only the apply mutation does, and even that
 * re-resolves from scratch server-side (weather-manager.md D7): a client can never hand the
 * server a pre-resolved preset and call it staged.
 *
 * Overrides are kept sparse, like `positionSlice.setupOverrides`: an untouched field must
 * keep the preset's resolved value, so this is an overlay — a `WeatherSetup` in its own
 * right — and never a full copy of the resolved state.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { WeatherPresetId, WeatherSetup } from '../../api/models';
import { airportSelected } from '../position/positionSlice';

export interface WeatherUiState {
  /** The staged preset, or `null` when nothing is staged. */
  selectedPresetId: WeatherPresetId | null;
  /** The instructor's edits on top of the staged preset. Sparse. */
  overrides: WeatherSetup;
  /** True while something is staged — the editors and the staging bar render on it. */
  staged: boolean;
}

export const initialWeatherUiState: WeatherUiState = {
  selectedPresetId: null,
  overrides: {},
  staged: false,
};

export type WeatherSource = 'preset' | 'manual';

/** `null` when nothing is staged; `'preset'` or `'manual'` otherwise. */
export function weatherSource(ui: WeatherUiState): WeatherSource | null {
  if (!ui.staged) return null;
  return ui.selectedPresetId === null ? 'manual' : 'preset';
}

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
      action: PayloadAction<{ field: keyof WeatherSetup; value: unknown }>,
    ) {
      if (!state.staged) {
        state.staged = true;
      }
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
