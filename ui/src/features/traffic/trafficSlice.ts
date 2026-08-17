import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

/**
 * Client-only UI state of the Traffic panel: which card was last used and the spawn
 * parameters. Server state (manifest, active entities) lives in RTK Query
 * (`trafficApi.ts`), never here.
 */

export const COUNT_MIN = 1;
export const COUNT_MAX = 4;
export const DISTANCE_MIN_NM = 2;
export const DISTANCE_MAX_NM = 20;

export interface TrafficUiState {
  /** The last spawn card tapped, or `null` before the first tap. Display-only. */
  selectedSpawnKind: string | null;
  params: {
    /** Entities per spawn for the plain-kind cards, clamped to 1–4. */
    count: number;
    /** Spawn distance in NM where the template uses one, clamped to 2–20. */
    distanceNm: number;
  };
}

export const initialTrafficUiState: TrafficUiState = {
  selectedSpawnKind: null,
  params: { count: 1, distanceNm: 8 },
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)));
}

const trafficSlice = createSlice({
  name: 'traffic',
  initialState: initialTrafficUiState,
  reducers: {
    spawnKindSelected(state, action: PayloadAction<string | null>) {
      state.selectedSpawnKind = action.payload;
    },
    /** Stepper writes clamp instead of rejecting — a stepper cannot show an error. */
    countChanged(state, action: PayloadAction<number>) {
      state.params.count = clamp(action.payload, COUNT_MIN, COUNT_MAX);
    },
    distanceChanged(state, action: PayloadAction<number>) {
      state.params.distanceNm = clamp(action.payload, DISTANCE_MIN_NM, DISTANCE_MAX_NM);
    },
  },
});

export const { spawnKindSelected, countChanged, distanceChanged } = trafficSlice.actions;
export default trafficSlice.reducer;
