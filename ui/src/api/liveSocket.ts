/**
 * The one WebSocket subscription in the app, shared by every live server stream.
 *
 * The server pushes two continuous feeds — `WS /ws/state` (aircraft, 4 Hz) and
 * `WS /ws/traffic` (contacts, 2 Hz) — and they differ only in what a frame *means*.
 * Everything around that is identical and is here: resolve the URL against the page
 * origin so LAN/tablet access just works, parse each frame as JSON, drop a malformed one
 * rather than tearing the link down, and reconnect for ever with capped, jittered backoff
 * because the instructor station is expected to outlive simulator restarts without anyone
 * touching the browser.
 *
 * Validating a frame is deliberately *not* here: the socket is an untyped byte pipe, and
 * only the caller knows what shape it asked for. `onFrame` receives parsed JSON as
 * `unknown` and each consumer runs its own guard (`isAircraftState`,
 * `isTrafficContactList`).
 */

import { useEffect, useRef } from 'react';

const INITIAL_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 10_000;

/** Resolves a socket path against the page origin, so LAN/tablet access just works. */
export function socketUrl(path: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${path}`;
}

/** Exponential backoff, capped, with jitter so reconnects do not synchronise. */
export function backoffDelayMs(attempt: number): number {
  const exponential = INITIAL_BACKOFF_MS * 2 ** Math.max(0, attempt);
  const capped = Math.min(exponential, MAX_BACKOFF_MS);
  return Math.round(capped * (0.75 + Math.random() * 0.5));
}

export interface LiveSocketHandlers {
  /** About to open (or re-open) the socket. */
  readonly onConnecting?: () => void;
  /** The socket is open and frames are expected. */
  readonly onOpen?: () => void;
  /** One parsed JSON frame. Validate it before trusting it. */
  readonly onFrame: (payload: unknown) => void;
  /** The link went down, or never came up. Called once per lost connection. */
  readonly onDropped: (reason: string) => void;
}

/**
 * Keep `path` connected for the lifetime of the component, feeding frames to `handlers`.
 *
 * `handlers` is read through a ref, so a caller re-rendering with fresh closures never
 * tears the socket down — only a changed `path` does.
 */
export function useLiveSocket(path: string, handlers: LiveSocketHandlers): void {
  // Refs, not state: reconnection bookkeeping must never trigger a render.
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number | null>(null);
  const attemptRef = useRef(0);
  const handlersRef = useRef(handlers);

  useEffect(() => {
    handlersRef.current = handlers;
  });

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
      handlersRef.current.onDropped(reason);
      const delay = backoffDelayMs(attemptRef.current);
      attemptRef.current += 1;
      clearTimer();
      timerRef.current = window.setTimeout(connect, delay);
    };

    function connect(): void {
      if (disposed) {
        return;
      }
      handlersRef.current.onConnecting?.();

      let socket: WebSocket;
      try {
        socket = new WebSocket(socketUrl(path));
      } catch (error) {
        scheduleReconnect(
          error instanceof Error ? error.message : `Could not open ${path}`,
        );
        return;
      }
      socketRef.current = socket;

      socket.addEventListener('open', () => {
        if (disposed) {
          return;
        }
        attemptRef.current = 0;
        handlersRef.current.onOpen?.();
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
        handlersRef.current.onFrame(parsed);
      });

      socket.addEventListener('close', (event: CloseEvent) => {
        socketRef.current = null;
        const reason =
          event.reason.length > 0
            ? event.reason
            : `${path} closed (code ${String(event.code)})`;
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
  }, [path]);
}
