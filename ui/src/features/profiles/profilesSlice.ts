/**
 * Client state for the Profiles panel — and nothing else.
 *
 * Saved profiles are **server state** and live in RTK Query (`profilesApi.ts`). What is
 * here is only the Save form's own draft: a name/description/author the instructor is
 * about to submit, whether to snapshot the currently staged weather, and a locally-built
 * failure list — Failures has no "staged" concept to read (a failure fires immediately or
 * arms on `POST`, `failures-manager.md` D13), so the list an instructor is composing for a
 * *new* profile has nowhere else to live until it is submitted with the rest of the draft.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { FailureId, FailureTrigger } from '../../api/models';

/** One failure entry the Save form has composed, before submission. */
export interface ProfileFailureDraft {
  failureId: FailureId;
  engineIndex: number | null;
  /** `null` = injected immediately when the profile is applied. Set = armed with this trigger. */
  trigger: FailureTrigger | null;
}

export interface SaveDraft {
  name: string;
  description: string;
  author: string;
  /** Snapshot `state.weather.staged`'s preset + overrides into the saved profile when true. */
  includeWeather: boolean;
  failures: ProfileFailureDraft[];
}

export interface ProfilesState {
  saveDraft: SaveDraft;
}

const initialSaveDraft: SaveDraft = {
  name: '',
  description: '',
  author: '',
  includeWeather: false,
  failures: [],
};

export const initialProfilesState: ProfilesState = {
  saveDraft: initialSaveDraft,
};

const profilesSlice = createSlice({
  name: 'profiles',
  initialState: initialProfilesState,
  reducers: {
    saveDraftNameChanged(state, action: PayloadAction<string>) {
      state.saveDraft.name = action.payload;
    },
    saveDraftDescriptionChanged(state, action: PayloadAction<string>) {
      state.saveDraft.description = action.payload;
    },
    saveDraftAuthorChanged(state, action: PayloadAction<string>) {
      state.saveDraft.author = action.payload;
    },
    saveDraftIncludeWeatherToggled(state) {
      state.saveDraft.includeWeather = !state.saveDraft.includeWeather;
    },
    saveDraftFailureAdded(state, action: PayloadAction<ProfileFailureDraft>) {
      state.saveDraft.failures.push(action.payload);
    },
    saveDraftFailureRemoved(state, action: PayloadAction<number>) {
      state.saveDraft.failures.splice(action.payload, 1);
    },
    /** Submitted, or dismissed: either way the draft goes away whole. */
    saveDraftReset() {
      return initialProfilesState;
    },
  },
});

export const {
  saveDraftNameChanged,
  saveDraftDescriptionChanged,
  saveDraftAuthorChanged,
  saveDraftIncludeWeatherToggled,
  saveDraftFailureAdded,
  saveDraftFailureRemoved,
  saveDraftReset,
} = profilesSlice.actions;

export default profilesSlice.reducer;
