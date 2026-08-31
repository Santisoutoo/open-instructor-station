/**
 * Camera Manager endpoints injected into the shared API slice —
 * `server/camera_routes.py`.
 *
 * The shape is the Profiles panel's (`features/profiles/profilesApi.ts`): a saved-item
 * list with create/apply/delete, invalidated through one tag. What differs is what is
 * *not* here — `setCameraView` invalidates nothing, because there is no server-held
 * camera state to refetch. `SimAdapter` exposes no read of the current named view (D6),
 * so the panel's highlight is client state in `cameraSlice` and reconciling it against a
 * server read is not merely unimplemented, it is impossible to do honestly.
 *
 * `applyCameraPosition` invalidates `CameraPositions` **only when it fails**: the one
 * failure it has that the list can fix is a 404, which means the id the panel offered no
 * longer exists — so the list, not the camera, is what is stale.
 */

import { instructorApi } from '../../api/instructorApi';
import type {
  CameraCommandResult,
  CameraManifest,
  CameraViewId,
  SavedCameraPosition,
} from '../../api/models';

export const cameraApi = instructorApi.injectEndpoints({
  endpoints: (builder) => ({
    /**
     * Per-view support plus the custom-positions tier. Capability-free: it answers even
     * when the answer is "nothing, and here is why" for every entry, which is exactly
     * what the panel needs to disable a control *with a reason* rather than hide it.
     */
    getCameraManifest: builder.query<CameraManifest, void>({
      query: () => 'camera/manifest',
    }),
    /** Switch to a named view now — momentary, fired straight from the tap (D6). */
    setCameraView: builder.mutation<CameraCommandResult, CameraViewId>({
      query: (viewId) => ({
        url: 'camera/view',
        method: 'POST',
        body: { view_id: viewId },
      }),
    }),
    /** Every saved position, in creation order. Local storage, never a simulator read. */
    getCameraPositions: builder.query<SavedCameraPosition[], void>({
      query: () => 'camera/positions',
      providesTags: ['CameraPositions'],
    }),
    /**
     * Capture the camera's current free pose under a name. The server assigns the id and
     * the timestamp; 409 when there is no live pose to capture.
     */
    saveCameraPosition: builder.mutation<SavedCameraPosition, string>({
      query: (name) => ({ url: 'camera/positions', method: 'POST', body: { name } }),
      invalidatesTags: ['CameraPositions'],
    }),
    /** Recall one, resolved fresh against live aircraft state (D4). */
    applyCameraPosition: builder.mutation<CameraCommandResult, string>({
      query: (positionId) => ({
        url: `camera/positions/${positionId}/apply`,
        method: 'POST',
      }),
      invalidatesTags: (_result, error) => (error ? ['CameraPositions'] : []),
    }),
    /** Remove one. Never capability-gated — nothing reaches the simulator. */
    deleteCameraPosition: builder.mutation<void, string>({
      query: (positionId) => ({ url: `camera/positions/${positionId}`, method: 'DELETE' }),
      invalidatesTags: ['CameraPositions'],
    }),
  }),
});

export const {
  useGetCameraManifestQuery,
  useSetCameraViewMutation,
  useGetCameraPositionsQuery,
  useSaveCameraPositionMutation,
  useApplyCameraPositionMutation,
  useDeleteCameraPositionMutation,
} = cameraApi;
