import { useLiveSocket, socketUrl } from '../../api/liveSocket';
import { isAircraftState } from '../../api/models';
import {
  connectionEstablished,
  connectionFailed,
  connectionOpening,
} from '../../store/connectionSlice';
import { useAppDispatch } from '../../store';
import { telemetryCleared, telemetryFrameReceived } from './telemetrySlice';

/** Same-origin path; the Vite dev server proxies it to the backend on :8000. */
export const TELEMETRY_SOCKET_PATH = '/ws/state';

/** Resolves the socket URL against the page origin, so LAN/tablet access just works. */
export function telemetrySocketUrl(path: string = TELEMETRY_SOCKET_PATH): string {
  return socketUrl(path);
}

export { backoffDelayMs } from '../../api/liveSocket';

/**
 * Opens `WS /ws/state`, pushes every validated frame into the telemetry slice and keeps
 * `connectionSlice` in sync. The connection lifetime — reconnect, backoff, malformed
 * frames — belongs to `api/liveSocket.ts`, shared with `WS /ws/traffic`; what is here is
 * only what makes this stream *aircraft state*: the guard and the two slices it feeds.
 *
 * Mounted once, at the top of the tree.
 */
export function useTelemetrySocket(path: string = TELEMETRY_SOCKET_PATH): void {
  const dispatch = useAppDispatch();

  useLiveSocket(path, {
    onConnecting: () => dispatch(connectionOpening()),
    onOpen: () => dispatch(connectionEstablished()),
    onFrame: (payload) => {
      if (isAircraftState(payload)) {
        dispatch(telemetryFrameReceived({ state: payload, receivedAt: Date.now() }));
      }
    },
    onDropped: (reason) => {
      dispatch(connectionFailed(reason));
      // Drop the last known state, so the panel shows "no data" instead of silently
      // displaying a stale position as if it were live.
      dispatch(telemetryCleared());
    },
  });
}
