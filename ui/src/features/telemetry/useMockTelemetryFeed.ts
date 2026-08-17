import { useEffect } from 'react';
import { useAppDispatch, useAppSelector } from '../../store';
import { mockFrame } from './mockFeed';
import { telemetryCleared, telemetryFrameReceived } from './telemetrySlice';

/** Matches the ~4 Hz cadence of the real `/ws/state` feed. */
const FRAME_INTERVAL_MS = 250;

/**
 * Drives the telemetry slice from the demo circuit while there is no simulator to do
 * it. Mounted once in `App`, right next to `useTelemetrySocket`, and inert unless the
 * demo feed is switched on *and* the sim link is down — the real socket always wins.
 *
 * Frames go through `telemetryFrameReceived`, the same action the socket dispatches,
 * so every consumer exercises its post-integration code path against demo data.
 */
export function useMockTelemetryFeed(): void {
  const dispatch = useAppDispatch();
  const demoFeed = useAppSelector((state) => state.ui.demoFeed);
  const connected = useAppSelector((state) => state.connection.status === 'connected');

  useEffect(() => {
    if (!demoFeed || connected) {
      return;
    }
    const startedAt = Date.now();
    const interval = setInterval(() => {
      dispatch(
        telemetryFrameReceived({
          state: mockFrame(Date.now() - startedAt),
          receivedAt: Date.now(),
        }),
      );
    }, FRAME_INTERVAL_MS);
    return () => {
      clearInterval(interval);
      // Same contract as a lost link: never leave a stale frame looking live.
      dispatch(telemetryCleared());
    };
  }, [demoFeed, connected, dispatch]);
}
