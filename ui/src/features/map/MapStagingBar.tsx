/**
 * The bar under the map while a reposition is staged: the picked coordinates and the
 * two commit paths (map design D5) — never a third write path.
 *
 * - **Apply here** commits immediately through the *identical* `POST
 *   /api/position/apply` mutation the Position panel's own commit button calls,
 *   carrying the aircraft's last telemetry frame onto the new point (D6): altitude,
 *   heading and IAS travel with the drag, so a repositioned aircraft arrives
 *   configured rather than dropped. Gated by the Position Manager's own
 *   `commitGate`, imported, never reimplemented (D8). A failed apply renders the
 *   server's error `detail` inline, verbatim — the same prose contract every other
 *   panel honours. Never a modal.
 * - **Send to Position tab** is the hand-off for an instructor who wants to edit the
 *   full setup before committing — the map never commits a placement itself, and the
 *   Position panel's staging bar remains the only place that happens. That takes
 *   **two** dispatches, and both are load-bearing. `placementStaged` is the shared
 *   server-intent contract `features/profiles` reads, staged with the same
 *   telemetry-carried defaults as Apply here (D6 covers both commit paths — the
 *   flight the aircraft is in should survive either door), with the nullable
 *   heading/IAS coalesced to the Position tab's own explicit-zero convention
 *   (`CoordinateForm`'s: 0 kt means "a point on the ground", stated, not guessed).
 *   `coordinateHandoffReceived` is what the Position *screen* consumes — it adopts
 *   the coordinate into the Custom location tab, so the point survives the screen's
 *   own staging mirror and can be placed. Staging alone would leave the coordinate
 *   visible to nobody and overwritten by the first placement the screen resolves.
 */

import {
  useApplyPlacementMutation,
  useGetCapabilitiesQuery,
} from '../../api/instructorApi';
import { useAppDispatch, useAppSelector } from '../../store';
import { tabSelected as moduleTabSelected } from '../../store/uiSlice';
import { coordinateHandoffReceived } from '../position/positionDesignSlice';
import { errorMessage } from '../position/errors';
import { commitGate } from '../position/gate';
import {
  placementStaged,
  tabSelected as positionTabSelected,
} from '../position/positionSlice';
import { type LatLon } from './measure';
import { modeSelected, stagedDiscarded } from './mapSlice';
import { defaultCoordinateRequest } from './reposition';

export function MapStagingBar({ staged }: { staged: LatLon }) {
  const dispatch = useAppDispatch();
  const mode = useAppSelector((state) => state.map.mode);
  const telemetry = useAppSelector((state) => state.telemetry.latest);

  const { data: capabilities, isError: capabilitiesFailed } = useGetCapabilitiesQuery();
  const gate = commitGate(capabilities, capabilitiesFailed);
  const [applyPlacement, applyState] = useApplyPlacementMutation();

  /** Consume the staging and drop an armed tool back to pan. */
  function disarm(): void {
    dispatch(stagedDiscarded());
    if (mode !== 'pan') {
      // Selecting the armed mode again is the slice's way back to pan.
      dispatch(modeSelected(mode));
    }
  }

  function applyHere(): void {
    void applyPlacement({
      placement: defaultCoordinateRequest(staged, telemetry),
      setup: null,
    })
      .unwrap()
      .then(() => {
        // The aircraft marker jumping to the point is the visible confirmation.
        disarm();
      })
      .catch(() => {
        // Rendered from applyState.error below; the staging stays for a retry.
      });
  }

  return (
    <div className="map-staging" role="region" aria-label="Staged map position">
      <span className="map-staging__label">Staged position</span>
      <span className="map-staging__coords">
        {staged.lat.toFixed(5)}, {staged.lon.toFixed(5)}
      </span>
      {!gate.open && <p className="map-staging__blocked">{gate.reason}</p>}
      {applyState.isError && (
        <p className="panel__error">
          {errorMessage(applyState.error, 'The aircraft could not be placed here.')}
        </p>
      )}
      <div className="map-staging__actions">
        <button
          type="button"
          className="ghost-button"
          onClick={() => {
            dispatch(stagedDiscarded());
          }}
        >
          Discard
        </button>
        <button
          type="button"
          className="ghost-button"
          onClick={() => {
            const request = defaultCoordinateRequest(staged, telemetry);
            dispatch(
              placementStaged({
                ...request,
                heading_deg: request.heading_deg ?? 0,
                ias_kt: request.ias_kt ?? 0,
              }),
            );
            dispatch(
              coordinateHandoffReceived({
                latitude: staged.lat,
                longitude: staged.lon,
                altitudeFt: 0,
                headingDeg: 0,
              }),
            );
            dispatch(positionTabSelected('coordinate'));
            dispatch(moduleTabSelected('position'));
            disarm();
          }}
        >
          Send to Position tab
        </button>
        <button
          type="button"
          className="map-staging__send"
          disabled={!gate.open || applyState.isLoading}
          onClick={applyHere}
        >
          {applyState.isLoading ? 'Placing…' : 'Apply here'}
        </button>
      </div>
    </div>
  );
}
