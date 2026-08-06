import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import { telemetryFrameReceived } from '../features/telemetry/telemetrySlice';

export type ConnectionStatus = 'idle' | 'connecting' | 'connected' | 'error';

export interface ConnectionState {
  status: ConnectionStatus;
  /** Human-readable reason for the last failure; cleared on a successful connect. */
  lastError: string | null;
  /** `Date.now()` of the last telemetry frame, whatever the current status. */
  lastUpdateAt: number | null;
  /** Consecutive failed attempts, drives the reconnect backoff shown in the UI. */
  reconnectAttempts: number;
}

export const initialConnectionState: ConnectionState = {
  status: 'idle',
  lastError: null,
  lastUpdateAt: null,
  reconnectAttempts: 0,
};

const connectionSlice = createSlice({
  name: 'connection',
  initialState: initialConnectionState,
  reducers: {
    connectionOpening(state) {
      state.status = 'connecting';
    },
    connectionEstablished(state) {
      state.status = 'connected';
      state.lastError = null;
      state.reconnectAttempts = 0;
    },
    connectionFailed(state, action: PayloadAction<string>) {
      state.status = 'error';
      state.lastError = action.payload;
      state.reconnectAttempts += 1;
    },
    connectionClosed(state) {
      state.status = 'idle';
    },
  },
  extraReducers: (builder) => {
    // The freshness timestamp is derived from the telemetry feed rather than dispatched
    // separately, so the two can never disagree.
    builder.addCase(telemetryFrameReceived, (state, action) => {
      state.lastUpdateAt = action.payload.receivedAt;
    });
  },
});

export const {
  connectionOpening,
  connectionEstablished,
  connectionFailed,
  connectionClosed,
} = connectionSlice.actions;

export default connectionSlice.reducer;
