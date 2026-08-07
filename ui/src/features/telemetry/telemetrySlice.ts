import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { AircraftState } from '../../api/models';

export interface TelemetryState {
  /** Most recent validated frame, or `null` before the first one arrives. */
  latest: AircraftState | null;
  /** `Date.now()` of that frame. */
  receivedAt: number | null;
  /** Frames accepted since the last reset — a cheap sanity signal for the ~4 Hz feed. */
  frameCount: number;
}

export const initialTelemetryState: TelemetryState = {
  latest: null,
  receivedAt: null,
  frameCount: 0,
};

export interface TelemetryFrame {
  state: AircraftState;
  receivedAt: number;
}

const telemetrySlice = createSlice({
  name: 'telemetry',
  initialState: initialTelemetryState,
  reducers: {
    /** A validated `AircraftState` frame arrived (WebSocket, or the `/api/state` seed). */
    telemetryFrameReceived(state, action: PayloadAction<TelemetryFrame>) {
      state.latest = action.payload.state;
      state.receivedAt = action.payload.receivedAt;
      state.frameCount += 1;
    },
    /**
     * Drop the last known state. Dispatched when the link is lost, so the panel shows
     * "no data" instead of silently displaying a stale position as if it were live.
     */
    telemetryCleared() {
      return initialTelemetryState;
    },
  },
});

export const { telemetryFrameReceived, telemetryCleared } = telemetrySlice.actions;
export default telemetrySlice.reducer;
