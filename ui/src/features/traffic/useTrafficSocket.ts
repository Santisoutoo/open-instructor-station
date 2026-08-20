/**
 * `WS /ws/traffic` → the traffic slice (design D10, §7.2).
 *
 * The same subscription `WS /ws/state` uses — `api/liveSocket.ts` owns the connection,
 * the reconnection and the JSON parsing — with the two things that make this stream
 * traffic layered on top: the `isTrafficContactList` guard, and the slice actions that
 * replace the contact list wholesale (every frame is the full picture, never a diff).
 *
 * **Never gated.** The stream is capability-free by contract: an adapter without
 * `can_spawn_traffic` streams `[]` for ever, so this hook is mounted unconditionally and
 * a station talking to a simulator with no bridge simply sees an empty sky — it never
 * sees an error, and the panel's gate is what tells the instructor why nothing can be
 * spawned.
 *
 * A dropped link does **not** clear the contacts, unlike telemetry's: the last frame is
 * the last honest picture and the panel labels it stale, where zeroing it would read as
 * "the sky is empty" when the truth is "I stopped hearing".
 */

import { useLiveSocket } from '../../api/liveSocket';
import { isTrafficContactList } from '../../api/models';
import { useAppDispatch } from '../../store';
import { trafficFrameReceived, trafficStreamDisconnected } from './trafficSlice';

/** Same-origin path; the Vite dev server proxies it to the backend on :8000. */
export const TRAFFIC_SOCKET_PATH = '/ws/traffic';

export function useTrafficSocket(path: string = TRAFFIC_SOCKET_PATH): void {
  const dispatch = useAppDispatch();

  useLiveSocket(path, {
    onFrame: (payload) => {
      if (isTrafficContactList(payload)) {
        dispatch(trafficFrameReceived(payload));
      }
    },
    onDropped: () => dispatch(trafficStreamDisconnected()),
  });
}
