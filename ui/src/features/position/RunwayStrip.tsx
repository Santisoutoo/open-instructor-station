/**
 * One tab per runway end of the loaded airport, each showing its own computed wind, a facts
 * row for the selected end, and the commanded Wind/QNH readouts.
 *
 * Selecting a runway here is one of the two places the screen mirrors onto the shared
 * `positionSlice`: `runwaySelected(ident)` is dispatched alongside the design slice's own
 * `startRunwaySelected`, guarded so re-selecting the same end is a no-op on the shared slice
 * (it wipes staged placements and overrides otherwise).
 *
 * There is no helipad tab. The v3 mockup had one because its sample airport table invented
 * one; `GET …/runways` publishes runway ends, and until navdata serves helipads there is
 * nothing behind such a tab but a label.
 */

import { useEffect } from 'react';
import { useAppDispatch, useAppSelector } from '../../store';
import { FactRow } from './FactRow';
import {
  formatDegrees,
  formatIlsFrequency,
  formatRunwayLength,
  formatSurface,
} from './format';
import { startRunwaySelected } from './positionDesignSlice';
import { runwaySelected } from './positionSlice';
import { useIls, useRunways, useSelectedRunway, useWeather } from './usePositionData';
import { runwayWind } from './wind';

export function RunwayStrip() {
  const dispatch = useAppDispatch();
  const selectedRunway = useAppSelector((state) => state.positionDesign.selectedRunway);
  const selectedStand = useAppSelector((state) => state.positionDesign.selectedStand);
  const legacyRunwayIdent = useAppSelector((state) => state.position.selectedRunwayIdent);

  const { runways, isError } = useRunways();
  const active = useSelectedRunway();
  const { ils, hasIls } = useIls(active?.ident ?? null);
  const { wind, qnhHpa, supported } = useWeather();

  const first = runways[0];

  // A runway end is the anchor for everything on the Approach tab, so the screen picks the
  // first one the index publishes rather than opening on an empty diagram. It only fires
  // when nothing is selected and no stand is chosen — re-selecting would fight the
  // instructor, and clearing would fight the Start-at popover.
  useEffect(() => {
    if (selectedRunway === null && selectedStand === null && first !== undefined) {
      dispatch(startRunwaySelected(first.ident));
      if (legacyRunwayIdent !== first.ident) {
        dispatch(runwaySelected(first.ident));
      }
    }
  }, [dispatch, selectedRunway, selectedStand, first, legacyRunwayIdent]);

  function selectRunway(ident: string) {
    dispatch(startRunwaySelected(ident));
    if (legacyRunwayIdent !== ident) {
      dispatch(runwaySelected(ident));
    }
  }

  return (
    <section className="pos-runwaystrip" aria-label="Runway">
      <div className="pos-runwaystrip__tabs" role="tablist" aria-label="Runway end">
        {runways.map((runway) => {
          const runwayWindText =
            wind === null
              ? null
              : runwayWind(wind.directionDeg, wind.speedKt, runway.true_bearing_deg);
          const isSelected = runway.ident === selectedRunway;
          return (
            <button
              key={runway.ident}
              type="button"
              role="tab"
              aria-selected={isSelected}
              aria-label={runway.ident}
              className={
                isSelected
                  ? 'pos-runwaystrip__tab pos-runwaystrip__tab--selected'
                  : 'pos-runwaystrip__tab'
              }
              onClick={() => {
                selectRunway(runway.ident);
              }}
            >
              <span className="pos-mono pos-runwaystrip__ident">{runway.ident}</span>
              {runwayWindText !== null && (
                <span
                  className={
                    runwayWindText.caution
                      ? 'pos-runwaystrip__wind pos-runwaystrip__wind--caution'
                      : 'pos-runwaystrip__wind'
                  }
                >
                  {runwayWindText.text}
                </span>
              )}
            </button>
          );
        })}
        {isError && (
          <p className="pos-runwaystrip__empty">
            The runways of this airport could not be read.
          </p>
        )}
      </div>

      {active !== null && (
        <div className="pos-runwaystrip__facts">
          <FactRow label="Length" value={formatRunwayLength(active.length_m)} />
          <FactRow label="Surface" value={formatSurface(active.surface)} />
          <FactRow
            label="Elevation"
            value={`${String(Math.round(active.elevation_ft))} ft`}
          />
          <FactRow label="Course" value={`${formatDegrees(active.true_bearing_deg)}°T`} />
          <FactRow
            label="ILS"
            value={
              ils !== null
                ? formatIlsFrequency(ils.frequency_khz)
                : hasIls === null
                  ? 'reading…'
                  : 'not available'
            }
          />
        </div>
      )}

      <div className="pos-runwaystrip__readouts">
        <FactRow
          label="Wind"
          value={
            wind === null
              ? supported === false
                ? 'not available'
                : 'reading…'
              : `${formatDegrees(wind.directionDeg)}° ${String(Math.round(wind.speedKt))} kt`
          }
        />
        <FactRow
          label="QNH"
          value={qnhHpa === null ? '—' : `${String(Math.round(qnhHpa))} hPa`}
        />
      </div>
    </section>
  );
}
