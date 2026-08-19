/**
 * The bar under the map while a reposition is staged: the picked coordinates, and the
 * hand-off to the Position tab.
 *
 * The map never commits a placement itself — repositioning is the Position Manager's
 * job. "Send to Position tab" stages a coordinate placement over there (altitude, heading
 * and speed at 0, the ground-point defaults) and switches tabs, so the instructor lands
 * where the placement can actually be committed, with the full setup editor around it.
 *
 * That takes **two** dispatches, and both are load-bearing. `placementStaged` is the
 * shared server-intent contract `features/profiles` reads;
 * `coordinateHandoffReceived` is what the Position *screen* consumes — it adopts the
 * coordinate into the Custom location tab, so the point survives the screen's own
 * staging mirror and can be placed. Staging alone would leave the coordinate visible to
 * nobody and overwritten by the first placement the screen resolves.
 */

import { useAppDispatch, useAppSelector } from '../../store';
import { tabSelected as moduleTabSelected } from '../../store/uiSlice';
import { coordinateHandoffReceived } from '../position/positionDesignSlice';
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
