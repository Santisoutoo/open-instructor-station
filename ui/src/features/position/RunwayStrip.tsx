/**
 * One tab per runway end (04R, 22L, 04L, 22R, Heli), each showing its own computed wind, a
 * facts row for the selected end, and the shared Wind/QNH readouts.
 *
 * Selecting a runway here is one of the two places the replica mirrors onto the **legacy**
 * `positionSlice` (design doc, "The hard constraint"): `runwaySelected(ident)` is dispatched
 * alongside the design slice's own `startRunwaySelected`, guarded so re-selecting the same
 * end is a no-op on the legacy slice (it wipes staged placements/overrides otherwise).
 */

import { FactRow } from './FactRow';
import { formatIlsFrequency, formatRunwayLength } from './format';
import {
  RUNWAY_IDS,
  startRunwaySelected,
  type RunwayId,
} from './positionDesignSlice';
import { runwaySelected } from './positionSlice';
import { RUNWAYS, SAMPLE_QNH_HPA, SAMPLE_WIND } from './sampleData';
import { useAppDispatch, useAppSelector } from '../../store';
import { runwayWind } from './wind';

export function RunwayStrip() {
  const dispatch = useAppDispatch();
  const selectedRunway = useAppSelector((state) => state.positionDesign.selectedRunway);
  const legacyRunwayIdent = useAppSelector((state) => state.position.selectedRunwayIdent);

  function selectRunway(id: RunwayId) {
    dispatch(startRunwaySelected(id));
    if (legacyRunwayIdent !== id) {
      dispatch(runwaySelected(id));
    }
  }

  const active = selectedRunway !== null ? RUNWAYS[selectedRunway] : null;

  return (
    <section className="pos-runwaystrip" aria-label="Runway and helipad">
      <div className="pos-runwaystrip__tabs" role="tablist" aria-label="Runway or helipad">
        {RUNWAY_IDS.map((id) => {
          const runway = RUNWAYS[id];
          const wind =
            runway.kind === 'runway'
              ? runwayWind(SAMPLE_WIND.directionDeg, SAMPLE_WIND.speedKt, runway.courseDeg)
              : null;
          const isSelected = id === selectedRunway;
          return (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={isSelected}
              aria-label={id}
              className={
                isSelected
                  ? 'pos-runwaystrip__tab pos-runwaystrip__tab--selected'
                  : 'pos-runwaystrip__tab'
              }
              onClick={() => {
                selectRunway(id);
              }}
            >
              <span className="pos-mono pos-runwaystrip__ident">{id}</span>
              {wind !== null && (
                <span
                  className={
                    wind.caution
                      ? 'pos-runwaystrip__wind pos-runwaystrip__wind--caution'
                      : 'pos-runwaystrip__wind'
                  }
                >
                  {wind.text}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {active !== null && (
        <div className="pos-runwaystrip__facts">
          {active.kind === 'runway' ? (
            <>
              <FactRow label="Length" value={formatRunwayLength(active.lengthFt * 0.3048)} />
              <FactRow label="Surface" value={active.surface} />
              <FactRow label="Elevation" value={`${String(active.elevationFt)} ft`} />
              <FactRow label="Course" value={`${String(active.courseDeg).padStart(3, '0')}°`} />
              <FactRow
                label="ILS"
                value={
                  active.ils !== null ? formatIlsFrequency(active.ils.frequencyKhz) : 'not available'
                }
              />
            </>
          ) : (
            <>
              <FactRow label="Type" value={active.type} />
              <FactRow label="Elevation" value={`${String(active.elevationFt)} ft`} />
            </>
          )}
        </div>
      )}

      <div className="pos-runwaystrip__readouts">
        <FactRow label="Wind" value={`${String(SAMPLE_WIND.directionDeg)}° ${String(SAMPLE_WIND.speedKt)} kt`} />
        <FactRow label="QNH" value={`${String(SAMPLE_QNH_HPA)} hPa`} />
      </div>
    </section>
  );
}
