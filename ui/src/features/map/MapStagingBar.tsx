/**
 * The bar under the map while a reposition is staged: the picked coordinates, and the
 * hand-off to the Position tab.
 *
 * The map never commits a placement itself — repositioning is the Position Manager's
 * job. "Send to Position tab" stages a coordinate placement over there (the exact
 * payload the CoordinateForm builds: altitude, heading and speed at 0, the ground-point
 * defaults) and switches tabs, so the instructor lands on the staging bar that can
 * actually commit, with the full setup editor around it.
 */

import { useAppDispatch, useAppSelector } from '../../store';
import { tabSelected as moduleTabSelected } from '../../store/uiSlice';
import {
  placementStaged,
  tabSelected as positionTabSelected,
} from '../position/positionSlice';
import { type LatLon } from './measure';
import { modeSelected, stagedDiscarded } from './mapSlice';

export function MapStagingBar({ staged }: { staged: LatLon }) {
  const dispatch = useAppDispatch();
  const mode = useAppSelector((state) => state.map.mode);

  return (
    <div className="map-staging" role="region" aria-label="Staged map position">
      <span className="map-staging__label">Staged position</span>
      <span className="map-staging__coords">
        {staged.lat.toFixed(5)}, {staged.lon.toFixed(5)}
      </span>
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
          className="map-staging__send"
          onClick={() => {
            dispatch(
              placementStaged({
                type: 'coordinate',
                position: {
                  latitude: staged.lat,
                  longitude: staged.lon,
                  altitude_ft: 0,
                },
                heading_deg: 0,
                ias_kt: 0,
              }),
            );
            dispatch(positionTabSelected('coordinate'));
            dispatch(moduleTabSelected('position'));
            dispatch(stagedDiscarded());
            if (mode !== 'pan') {
              // Selecting the armed mode again is the slice's way back to pan.
              dispatch(modeSelected(mode));
            }
          }}
        >
          Send to Position tab
        </button>
      </div>
    </div>
  );
}
