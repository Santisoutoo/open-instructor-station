import { useEffect, useRef } from 'react';
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

const INITIAL_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 10_000;

/** Resolves the socket URL against the page origin, so LAN/tablet access just works. */
export function telemetrySocketUrl(path: string = TELEMETRY_SOCKET_PATH): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${path}`;
}

/** Exponential backoff, capped, with jitter so reconnects do not synchronise. */
export function backoffDelayMs(attempt: number): number {
  const exponential = INITIAL_BACKOFF_MS * 2 ** Math.max(0, attempt);
  const capped = Math.min(exponential, MAX_BACKOFF_MS);
  return Math.round(capped * (0.75 + Math.random() * 0.5));
}

/**
 * Opens `WS /ws/state`, pushes every validated frame into the telemetry slice and keeps
 * `connectionSlice` in sync. Reconnects for ever with exponential backoff — the instructor
 * station is expected to outlive simulator restarts without anyone touching the browser.
 *
 * Mounted once, at the top of the tree.
 */
export function useTelemetrySocket(path: string = TELEMETRY_SOCKET_PATH): void {
  const dispatch = useAppDispatch();

  // Refs, not state: reconnection bookkeeping must never trigger a render.
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number | null>(null);
  const attemptRef = useRef(0);

  useEffect(() => {
    let disposed = false;

    const clearTimer = () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    const scheduleReconnect = (reason: string) => {
      if (disposed) {
        return;
      }
      dispatch(connectionFailed(reason));
      dispatch(telemetryCleared());
      const delay = backoffDelayMs(attemptRef.current);
      attemptRef.current += 1;
      clearTimer();
      timerRef.current = window.setTimeout(connect, delay);
    };

    function connect(): void {
      if (disposed) {
        return;
      }
      dispatch(connectionOpening());

      let socket: WebSocket;
      try {
        socket = new WebSocket(telemetrySocketUrl(path));
      } catch (error) {
        scheduleReconnect(
          error instanceof Error ? error.message : 'Could not open the telemetry socket',
        );
        return;
      }
      socketRef.current = socket;

      socket.addEventListener('open', () => {
        if (disposed) {
          return;
        }
        attemptRef.current = 0;
        dispatch(connectionEstablished());
      });

      socket.addEventListener('message', (event: MessageEvent<unknown>) => {
        if (disposed || typeof event.data !== 'string') {
          return;
        }
        let parsed: unknown;
        try {
          parsed = JSON.parse(event.data);
        } catch {
          // A single malformed frame is not worth tearing the link down for.
          return;
        }
        if (isAircraftState(parsed)) {
          dispatch(telemetryFrameReceived({ state: parsed, receivedAt: Date.now() }));
        }
      });

      socket.addEventListener('close', (event: CloseEvent) => {
        socketRef.current = null;
        const reason =
          event.reason.length > 0
            ? event.reason
            : `Telemetry socket closed (code ${String(event.code)})`;
        scheduleReconnect(reason);
      });

      // 'error' is always followed by 'close'; reconnecting is handled there so the
      // attempt counter is only incremented once per lost connection.
      socket.addEventListener('error', () => {
        socketRef.current?.close();
      });
    }

    connect();

    return () => {
      disposed = true;
      clearTimer();
      const socket = socketRef.current;
      socketRef.current = null;
      if (socket !== null) {
        socket.close();
      }
    };
  }, [dispatch, path]);
}
