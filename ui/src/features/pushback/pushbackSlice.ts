/**
 * Client-only form state of the Pushback panel: the manoeuvre being described and the
 * request staged for execution. Server state (manifest, preview, execute) belongs to
 * RTK Query (`pushbackApi.ts`, the wiring wave), never here.
 *
 * Until that wave registers this slice in the store, `PushbackPanel` drives this exact
 * reducer through `useReducer` — same actions, same transitions, so lifting it into
 * `configureStore` later changes where the state lives and nothing about how it moves.
 *
 * Invariant the reducers protect: the form always describes a *valid*
 * `PushbackRequest` (design §3's model_validator) — `angle_deg` is 0 exactly when the
 * direction is 'straight', and within (0, max] otherwise — so the panel never stages a
 * request the backend would 422.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import {
  PUSHBACK_MAX_ANGLE_DEG,
  PUSHBACK_MAX_DISTANCE_M,
  type PushbackDirection,
  type PushbackRequest,
} from './types.mock';

/** Slider floors. The request model wants `distance_m > 0` and, on arcs, `angle_deg > 0`. */
export const PUSHBACK_DISTANCE_MIN_M = 1;
export const PUSHBACK_ANGLE_MIN_DEG = 1;

/** "Straight push, 20 m" is the one-tap default the design's two-tap budget names. */
export const PUSHBACK_DEFAULT_DISTANCE_M = 20;
/**
 * Seeded into `angleDeg` when the direction leaves 'straight' with the angle still 0,
 * so the form never describes the invalid "arc of 0°". 45° is a plain gate turn, not a
 * measured constant.
 */
export const PUSHBACK_DEFAULT_ARC_ANGLE_DEG = 45;

export interface PushbackFormState {
  direction: PushbackDirection;
  distanceM: number;
  angleDeg: number;
  /**
   * The request staged by Preview; `null` means Execute is disarmed. Any form edit
   * clears it — a stale preview must never be what Execute sends.
   */
  staged: PushbackRequest | null;
}

export const initialPushbackState: PushbackFormState = {
  direction: 'straight',
  distanceM: PUSHBACK_DEFAULT_DISTANCE_M,
  angleDeg: 0,
  staged: null,
};

/** The exact wire shape (§3) the staged form describes — asserted key-for-key in tests. */
export function toRequest(form: PushbackFormState): PushbackRequest {
  return {
    direction: form.direction,
    distance_m: form.distanceM,
    angle_deg: form.angleDeg,
  };
}

/** Slider writes clamp instead of rejecting — a slider cannot show an error. */
function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)));
}

const pushbackSlice = createSlice({
  name: 'pushback',
  initialState: initialPushbackState,
  reducers: {
    /**
     * D5 on the buttons: the direction is where the NOSE ends up. Switching to
     * 'straight' zeroes the angle (the §3 validator's demand); leaving 'straight'
     * with the angle still 0 seeds the default arc angle for the same reason.
     */
    directionSelected(state, action: PayloadAction<PushbackDirection>) {
      state.direction = action.payload;
      if (action.payload === 'straight') {
        state.angleDeg = 0;
      } else if (state.angleDeg === 0) {
        state.angleDeg = PUSHBACK_DEFAULT_ARC_ANGLE_DEG;
      }
      state.staged = null;
    },
    distanceChanged(state, action: PayloadAction<number>) {
      state.distanceM = clamp(
        action.payload,
        PUSHBACK_DISTANCE_MIN_M,
        PUSHBACK_MAX_DISTANCE_M,
      );
      state.staged = null;
    },
    /** Ignored while 'straight' — the slider is disabled then, and 0 must survive. */
    angleChanged(state, action: PayloadAction<number>) {
      if (state.direction === 'straight') {
        return;
      }
      state.angleDeg = clamp(
        action.payload,
        PUSHBACK_ANGLE_MIN_DEG,
        PUSHBACK_MAX_ANGLE_DEG,
      );
      state.staged = null;
    },
    /** Preview stages what the form describes right now; Execute sends it verbatim. */
    previewStaged(state) {
      state.staged = toRequest(state);
    },
    stagedDiscarded(state) {
      state.staged = null;
    },
  },
});

export const {
  directionSelected,
  distanceChanged,
  angleChanged,
  previewStaged,
  stagedDiscarded,
} = pushbackSlice.actions;

export default pushbackSlice.reducer;
