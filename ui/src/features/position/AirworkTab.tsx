import { FactRow } from './FactRow';
import { formatHeadingM, formatSpeedKt } from './format';
import { AIRWORK_LEVELS, airworkLevelSelected } from './positionDesignSlice';
import { AIRPORT_POSITION_LABEL, AIRWORK_LEVEL_FEET, AIRWORK_TICK_WIDTH_PX, RUNWAYS } from './sampleData';
import { useAppDispatch, useAppSelector } from '../../store';

export function AirworkTab() {
  const dispatch = useAppDispatch();
  const airworkLevel = useAppSelector((state) => state.positionDesign.airworkLevel);
  const selectedRunway = useAppSelector((state) => state.positionDesign.selectedRunway);
  const iasKt = useAppSelector((state) => state.positionDesign.config.iasKt);

  const runway = selectedRunway !== null ? RUNWAYS[selectedRunway] : null;
  const courseDeg = runway !== null && runway.kind === 'runway' ? runway.courseDeg : 0;

  return (
    <div
      id="pos-tabpanel-airwork"
      role="tabpanel"
      aria-labelledby="pos-tab-airwork"
      className="pos-airworktab"
    >
      <div className="pos-airworktab__ladder" role="radiogroup" aria-label="Airwork level">
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
        <FactRow label="Position" value={`Overhead LFMN · ${AIRPORT_POSITION_LABEL}`} />
        <FactRow label="Level" value={airworkLevel} />
        <FactRow label="IAS" value={formatSpeedKt(iasKt)} caution={iasKt < 150} />
        <FactRow label="Heading" value={formatHeadingM(courseDeg)} />
      </div>
    </div>
  );
}
