/**
 * Airwork: overhead the loaded airport, at one of four levels.
 *
 * The position is the airport's own coordinate out of navdata, sent as a
 * `CoordinatePlacementRequest`; the level is the one thing this screen decides, because a
 * flight level is a flight level. Heading follows the selected runway's course so the
 * aircraft starts pointing somewhere sensible rather than at true north.
 */

import { useAppDispatch, useAppSelector } from '../../store';
import { FactRow } from './FactRow';
import {
  AIRWORK_LEVEL_FEET,
  AIRWORK_MINIMUM_IAS_KT,
  AIRWORK_TICK_WIDTH_PX,
} from './airwork';
import {
  formatHeadingTrue,
  formatLatitude,
  formatLongitude,
  formatSpeedKt,
} from './format';
import { AIRWORK_LEVELS, airworkLevelSelected } from './positionDesignSlice';
import { useAirport, useSelectedRunway, useStagedPlacement } from './usePositionData';

export function AirworkTab() {
  const dispatch = useAppDispatch();
  const airworkLevel = useAppSelector((state) => state.positionDesign.airworkLevel);
  const { airport } = useAirport();
  const runway = useSelectedRunway();
  const { merged, preview } = useStagedPlacement();

  const iasKt = merged.ias_kt ?? preview?.placement.ias_kt ?? null;
  const position =
    airport === undefined
      ? null
      : `${formatLatitude(airport.position.latitude)} / ${formatLongitude(airport.position.longitude)}`;

  return (
    <div
      id="pos-tabpanel-airwork"
      role="tabpanel"
      aria-labelledby="pos-tab-airwork"
      className="pos-airworktab"
    >
      <div
        className="pos-airworktab__ladder"
        role="radiogroup"
        aria-label="Airwork level"
      >
        {AIRWORK_LEVELS.map((level) => (
          <button
            key={level}
            type="button"
            role="radio"
            aria-checked={level === airworkLevel}
            className={
              level === airworkLevel
                ? 'pos-airworktab__row pos-airworktab__row--selected'
                : 'pos-airworktab__row'
            }
            onClick={() => {
              dispatch(airworkLevelSelected(level));
            }}
          >
            <span
              className="pos-airworktab__tick"
              style={{ width: AIRWORK_TICK_WIDTH_PX[level] }}
            />
            <span className="pos-mono pos-airworktab__fl">{level}</span>
            <span className="pos-mono pos-airworktab__feet">
              {AIRWORK_LEVEL_FEET[level].toLocaleString('en-GB')} ft
            </span>
          </button>
        ))}
      </div>

      <div className="pos-airworktab__facts">
        <FactRow
          label="Position"
          value={
            position === null
              ? 'no airport loaded'
              : `Overhead ${airport?.icao ?? ''} · ${position}`
          }
        />
        <FactRow label="Level" value={airworkLevel} />
        <FactRow
          label="IAS"
          value={iasKt === null ? 'not resolved' : formatSpeedKt(iasKt)}
          caution={iasKt !== null && iasKt < AIRWORK_MINIMUM_IAS_KT}
        />
        <FactRow
          label="Heading"
          value={
            runway === null
              ? 'no runway selected'
              : formatHeadingTrue(runway.true_bearing_deg)
          }
        />
      </div>
    </div>
  );
}
