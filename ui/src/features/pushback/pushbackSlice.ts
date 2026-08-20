/**
 * Client-only form state of the Pushback panel: the manoeuvre being described and the
 * request staged for execution. Server state — the manifest, the preview, the result —
 * belongs to RTK Query (`pushbackApi.ts`), never here.
 *
 * That is also why the slider **bounds arrive on the action** rather than living in this
 * state or in a module constant: `max_distance_m`/`max_angle_deg` are server state, echoed
 * by `GET /api/pushback/manifest` precisely so the UI never holds a second copy of
 * `core.pushback.PushbackRequest`'s field constraints. The panel passes whatever the
 * manifest currently says; `undefined` means "not stated yet", and the gate has the panel
 * disabled in that case anyway.
 *
 * Invariant the reducers protect: the form always describes a *valid* `PushbackRequest`
 * (design §3's `model_validator`) — `angle_deg` is 0 exactly when the direction is
 * 'straight', and within (0, max] otherwise — so the panel never stages a request the
 * backend would 422.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { PushbackDirection, PushbackRequest } from '../../api/models';

/**
 * Slider floors. Unlike the ceilings these are genuinely the UI's own: the server asks
 * only for `distance_m > 0` and, on an arc, `angle_deg > 0`, and 1 is the granularity a
 * one-metre-per-step slider can express.
 */
export const PUSHBACK_DISTANCE_MIN_M = 1;
export const PUSHBACK_ANGLE_MIN_DEG = 1;

/** "Straight push, 20 m" is the one-tap default the design's two-tap budget names. */
export const PUSHBACK_DEFAULT_DISTANCE_M = 20;
/**
 * Seeded into `angleDeg` when the direction leaves 'straight' with the angle still 0, so
 * the form never describes the invalid "arc of 0°". 45° is a plain gate turn, not a
 * measured constant.
 */
export const PUSHBACK_DEFAULT_ARC_ANGLE_DEG = 45;

/**
 * A slider edit: the new value, plus the ceiling the manifest states right now.
 * `undefined` leaves the top open — there is nothing to clamp against yet.
 */
export interface PushbackSliderEdit {
  value: number;
  max: number | undefined;
}

export interface PushbackFormState {
  direction: PushbackDirection;
  distanceM: number;
  angleDeg: number;
  /**
   * The request staged by Preview; `null` means Execute is disarmed. Any form edit clears
   * it — a stale preview must never be what Execute sends.
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
function clamp(value: number, min: number, max: number | undefined): number {
  return Math.min(max ?? Number.POSITIVE_INFINITY, Math.max(min, Math.round(value)));
}

const pushbackSlice = createSlice({
  name: 'pushback',
  initialState: initialPushbackState,
  reducers: {
    /**
     * D5 on the buttons: the direction is where the NOSE ends up. Switching to 'straight'
     * zeroes the angle (the §3 validator's demand); leaving 'straight' with the angle
     * still 0 seeds the default arc angle for the same reason.
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
    distanceChanged(state, action: PayloadAction<PushbackSliderEdit>) {
      state.distanceM = clamp(
        action.payload.value,
        PUSHBACK_DISTANCE_MIN_M,
        action.payload.max,
      );
      state.staged = null;
    },
    /** Ignored while 'straight' — the slider is disabled then, and 0 must survive. */
    angleChanged(state, action: PayloadAction<PushbackSliderEdit>) {
      if (state.direction === 'straight') {
        return;
      }
      state.angleDeg = clamp(action.payload.value, PUSHBACK_ANGLE_MIN_DEG, action.payload.max);
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
