/**
 * Pushback endpoints injected into the shared API slice — never editing
 * `instructorApi.ts`'s endpoint map directly (design D10, the Fuel & Payload and
 * Weather precedent).
 *
 * `previewPushback` is a **query** despite being a POST: `server/pushback_routes.py`
 * writes nothing on preview — it reads `get_aircraft_state()` and resolves the geometry
 * — so modelling it as a query is what gives the panel RTK Query's caching and
 * de-duplication for free, the `previewPlacement`/`previewWeather` precedent.
 *
 * Nothing here invalidates a tag. There is no persisted pushback state on the server to
 * refresh: the aftermath of a push is the aircraft's live position, which arrives on the
 * telemetry WebSocket, and `PushbackResult.state` already carries the read-back.
 */

import { instructorApi } from '../../api/instructorApi';
import type {
  PushbackManifest,
  PushbackPreview,
  PushbackRequest,
  PushbackResult,
} from '../../api/models';

export const pushbackApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    /**
     * Capability + reason, and the exact `distance_m`/`angle_deg` bounds. Always 200.
     *
     * The bounds are the reason the panel reads this rather than `GET /api/capabilities`:
     * the manifest carries the same `can_pushback` truth *plus* the server's own sentence
     * for why not, and the two numbers the sliders need — so the panel never holds a
     * second, drifting copy of `PushbackRequest`'s field constraints.
     */
    getPushbackManifest: builder.query<PushbackManifest, void>({
      query: () => 'pushback/manifest',
    }),
    /**
     * Where the aircraft would end up and the path it would take. Writes nothing.
     *
     * Not capability-gated on the server (D6), but it *does* enforce the on-ground
     * precondition — 409 — so a preview never draws a path execute would refuse.
     */
    previewPushback: builder.query<PushbackPreview, PushbackRequest>({
      query: (request) => ({ url: 'pushback/preview', method: 'POST', body: request }),
    }),
    /**
     * Push the aircraft back. The one call that moves anything.
     *
     * **Not idempotent, on purpose**: the request states a manoeuvre relative to wherever
     * the aircraft is now, so replaying it pushes back a second time. The panel therefore
     * disarms itself after a successful push and makes the instructor preview again.
     */
    executePushback: builder.mutation<PushbackResult, PushbackRequest>({
      query: (request) => ({ url: 'pushback/execute', method: 'POST', body: request }),
    }),
  }),
});

export const {
  useGetPushbackManifestQuery,
  usePreviewPushbackQuery,
  useExecutePushbackMutation,
} = pushbackApi;
