import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import { telemetryCleared } from '../telemetry/telemetrySlice';
import type { ControlValue, WriteKey } from './controls';

/**
 * Optimistic write bookkeeping for the Aircraft Control panel.
 *
 * The feature spec is explicit about this: *"the panel is the first place where write
 * latency is visible to the instructor, so commands are optimistically applied in the UI
 * and reconciled against the next state frame — Redux Toolkit handles this with a
 * pending/confirmed flag per control."*
 *
 * Two maps, because reconciliation is not uniform:
 *
 * - `pending` — a write is in flight. The widget shows this value and is locked, so a
 *   double tap cannot queue two contradictory commands.
 * - `commanded` — the last value the server confirmed. This is the *only* record for
 *   flaps, gear, autobrake and lights: `AircraftState` carries none of them, so the live
 *   feed can never confirm them and `POST /api/aircraft/setup` echoing the applied setup
 *   is what closes the loop. Altitude, speed, heading and vertical speed *are* in the
 *   feed, and the panel prefers the live value over `commanded` for exactly that reason.
 *
 * Server state itself lives in RTK Query, never here.
 */
export interface AircraftControlsState {
  /** Last value the server confirmed, per control. */
  commanded: Partial<Record<WriteKey, ControlValue>>;
  /** Controls with a write in flight, and the value being written. */
  pending: Partial<Record<WriteKey, ControlValue>>;
  /** Last write failure, shown once at the top of the panel. */
  lastError: string | null;
}

export const initialAircraftControlsState: AircraftControlsState = {
  commanded: {},
  pending: {},
  lastError: null,
};

export interface ControlWrite {
  key: WriteKey;
  value: ControlValue;
}

export interface ControlWriteFailure {
  key: WriteKey;
  message: string;
}

const aircraftSlice = createSlice({
  name: 'aircraft',
  initialState: initialAircraftControlsState,
  reducers: {
    /** A write left for the server. Shown optimistically and locked until it resolves. */
    controlWriteStarted(state, action: PayloadAction<ControlWrite>) {
      state.pending[action.payload.key] = action.payload.value;
      state.lastError = null;
    },
    /** The server applied the write and echoed it back. */
    controlWriteSucceeded(state, action: PayloadAction<ControlWrite>) {
      delete state.pending[action.payload.key];
      state.commanded[action.payload.key] = action.payload.value;
      state.lastError = null;
    },
    /**
     * The write failed. The optimistic value is dropped rather than kept: showing a
     * position the aircraft is not in is worse than showing nothing.
     */
    controlWriteFailed(state, action: PayloadAction<ControlWriteFailure>) {
      delete state.pending[action.payload.key];
      state.lastError = action.payload.message;
    },
    /** Dismiss the error banner without touching any control. */
    controlErrorDismissed(state) {
      state.lastError = null;
    },
    /**
     * Forget everything the panel believes. Dispatched when the link drops: a stale
     * "gear down" is a lie once the station has lost sight of the aircraft.
     */
    aircraftControlsReset() {
      return initialAircraftControlsState;
    },
  },
  extraReducers: (builder) => {
    // Derived from the telemetry feed rather than dispatched separately, so the panel's
    // beliefs and the live picture can never disagree: when the link drops and the
    // telemetry slice is cleared, the last commanded gear position stops being evidence.
    builder.addCase(telemetryCleared, () => initialAircraftControlsState);
  },
});

export const {
  controlWriteStarted,
  controlWriteSucceeded,
  controlWriteFailed,
  controlErrorDismissed,
  aircraftControlsReset,
} = aircraftSlice.actions;

export default aircraftSlice.reducer;

/** The value the panel should show for a control, ignoring the live telemetry feed. */
export function selectControlValue(
  state: AircraftControlsState,
  key: WriteKey,
): ControlValue | undefined {
  return state.pending[key] ?? state.commanded[key];
}

/** True while a write for `key` is in flight. */
export function selectIsPending(state: AircraftControlsState, key: WriteKey): boolean {
  return state.pending[key] !== undefined;
}
