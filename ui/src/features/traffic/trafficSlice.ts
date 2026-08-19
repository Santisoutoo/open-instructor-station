/**
 * Traffic panel state — design §7.2.
 *
 * `contacts` and `connected` mirror the `WS /ws/traffic` stream: every frame replaces
 * the contact list wholesale (the stream pushes the full picture, never a diff), and
 * `connected` says whether frames are currently arriving — on a disconnect the last
 * frame is kept on screen and the panel labels it stale rather than pretending an empty
 * sky. `selectedShape` is client-only: which spawn form tab is open.
 *
 * The WebSocket wiring itself lands with the RTK Query wave (design Track C, second
 * slice); until then nothing dispatches `trafficFrameReceived` outside the tests.
 */

import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { TrafficContact, TrafficScenarioShape } from './types.mock';

export interface TrafficState {
  /** Replaced wholesale on every `/ws/traffic` frame. */
  contacts: TrafficContact[];
  /** True while the traffic stream is delivering frames. */
  connected: boolean;
  /** Which spawn form is open — client-only, never sent anywhere. */
  selectedShape: TrafficScenarioShape;
}

export const initialTrafficState: TrafficState = {
  contacts: [],
  connected: false,
  selectedShape: 'tcas_conflict',
};

const trafficSlice = createSlice({
  name: 'traffic',
  initialState: initialTrafficState,
  reducers: {
    /** One `/ws/traffic` frame: the full contact list, replacing whatever was there. */
    trafficFrameReceived(state, action: PayloadAction<TrafficContact[]>) {
      state.contacts = action.payload;
      state.connected = true;
    },
    /**
     * The stream dropped. The contacts are kept — they are the last honest picture and
     * the panel marks them stale via `connected` — never silently zeroed, which would
     * read as "the sky is empty" when the truth is "I stopped hearing".
     */
    trafficStreamDisconnected(state) {
      state.connected = false;
    },
    shapeSelected(state, action: PayloadAction<TrafficScenarioShape>) {
      state.selectedShape = action.payload;
    },
  },
});

export const { trafficFrameReceived, trafficStreamDisconnected, shapeSelected } =
  trafficSlice.actions;
export default trafficSlice.reducer;
