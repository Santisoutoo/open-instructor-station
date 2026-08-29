/**
 * The Camera tab: the five named views on top, the saved positions below.
 *
 * **Nothing here ever disappears.** The tab-level gate (`can_control_camera`) and the
 * per-view manifest both *disable* — hard rule 3, the `FailureRow` pattern. On X-Plane,
 * where the adapter has not yet declared the capability, that is the whole panel
 * rendered greyed out with the adapter's own sentence under every card, which is a far
 * more useful thing to hand an instructor than an empty tab.
 *
 * **A tap is the command.** No staging bar, no confirm (D6, and the Failures panel's
 * D13): switching view *is* the product, one tap. Because there is no honest read of the
 * simulator's current view, the highlight follows the last *request* — client state in
 * `cameraSlice`, never reconciled.
 *
 * **Failures stay separate.** Each region renders its own action's error through
 * `cameraError`, so a 409 ("switch to the drone camera first") is never dressed up as
 * the 501 that means "this will never work here". See `errors.ts`.
 */

import { useGetCapabilitiesQuery } from '../../api/instructorApi';
import { type CameraViewSupport } from '../../api/models';
import { useAppDispatch, useAppSelector } from '../../store';
import {
  useApplyCameraPositionMutation,
  useDeleteCameraPositionMutation,
  useGetCameraManifestQuery,
  useGetCameraPositionsQuery,
  useSaveCameraPositionMutation,
  useSetCameraViewMutation,
} from './cameraApi';
import {
  positionApplied,
  positionDeleted,
  saveDraftCleared,
  saveDraftNameChanged,
  viewRequested,
} from './cameraSlice';
import { cameraError } from './errors';
import { cameraGate } from './gate';
import { SavedPositions } from './SavedPositions';
import { ViewGrid } from './ViewGrid';
import './camera.css';

/** No manifest yet means no support entry, and a missing entry counts as unsupported. */
const NO_VIEWS: readonly CameraViewSupport[] = [];

/**
 * One failed action, stated. The `--kind` modifier is what keeps the four failures of
 * `errors.ts` visually distinct as well as textually distinct.
 */
function Notice({ error, fallback }: { error: unknown; fallback: string }) {
  const { kind, message } = cameraError(error, fallback);
  return (
    <p className={`panel__error camera-notice camera-notice--${kind}`} role="alert">
      {message}
    </p>
  );
}

export function CameraPanel() {
  const dispatch = useAppDispatch();
  const { lastRequestedView, selectedPositionId, saveDraftName } = useAppSelector(
    (state) => state.camera,
  );

  const capabilitiesQuery = useGetCapabilitiesQuery();
  const gate = cameraGate(capabilitiesQuery.data, capabilitiesQuery.isError);

  const manifestQuery = useGetCameraManifestQuery();
  const positionsQuery = useGetCameraPositionsQuery();

  const [setCameraView, viewState] = useSetCameraViewMutation();
  const [savePosition, saveState] = useSaveCameraPositionMutation();
  const [applyPosition, applyState] = useApplyCameraPositionMutation();
  const [deletePosition, deleteState] = useDeleteCameraPositionMutation();

  const manifest = manifestQuery.data;

  return (
    <section className="panel camera-panel" aria-labelledby="camera-heading">
      <h2 id="camera-heading">Camera</h2>

      {!gate.open && <p className="panel__empty">{gate.reason}</p>}
      {manifest?.caveat != null && <p className="camera-caveat">{manifest.caveat}</p>}
      {manifestQuery.isLoading && (
        <p className="panel__empty">Loading the camera manifest…</p>
      )}
      {manifestQuery.isError && (
        <p className="panel__error">
          The camera manifest could not be read, so every view is disabled.
        </p>
      )}

      <ViewGrid
        views={manifest?.views ?? NO_VIEWS}
        activeViewId={lastRequestedView}
        disabled={!gate.open}
        onSelectView={(viewId) => {
          // Momentary: the request goes out on the tap, and the highlight moves with it
          // rather than waiting for a reply that carries no new information (D6).
          dispatch(viewRequested(viewId));
          void setCameraView(viewId);
        }}
      />
      {viewState.isError && (
        <Notice error={viewState.error} fallback="The view could not be switched." />
      )}

      {positionsQuery.isError && (
        <p className="panel__error">The saved camera positions could not be loaded.</p>
      )}

      <SavedPositions
        positions={positionsQuery.data ?? []}
        selectedPositionId={selectedPositionId}
        customPositionsSupported={manifest?.custom_positions_supported ?? false}
        customPositionsReason={manifest?.custom_positions_reason ?? null}
        droneActive={lastRequestedView === 'drone'}
        disabled={!gate.open}
        draftName={saveDraftName}
        onDraftNameChanged={(name) => {
          dispatch(saveDraftNameChanged(name));
        }}
        onSaveCurrent={(name) => {
          // The form is cleared on success only: a 409 or a 422 leaves the name in place
          // so the instructor can fix the precondition and press Save again.
          void savePosition(name)
            .unwrap()
            .then(() => {
              dispatch(saveDraftCleared());
            })
            .catch(() => undefined);
        }}
        onApply={(positionId) => {
          dispatch(positionApplied(positionId));
          void applyPosition(positionId);
        }}
        onDelete={(positionId) => {
          dispatch(positionDeleted(positionId));
          void deletePosition(positionId);
        }}
      />
      {saveState.isError && (
        <Notice error={saveState.error} fallback="The position could not be saved." />
      )}
      {applyState.isError && (
        <Notice error={applyState.error} fallback="The position could not be recalled." />
      )}
      {deleteState.isError && (
        <Notice error={deleteState.error} fallback="The position could not be deleted." />
      )}
    </section>
  );
}
