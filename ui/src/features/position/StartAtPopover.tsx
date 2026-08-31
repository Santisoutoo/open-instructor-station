/**
 * The Start-at popover: the airport's runway ends and the parking-kind filter on the left,
 * its real diagram and a filtered, scrollable stand list on the right.
 *
 * Selecting a runway here is one of the two places the mirrored `runwaySelected` dispatch
 * happens (the other is the runway strip); both use the same same-value guard against the
 * shared `positionSlice`, which wipes staged placements and overrides when it fires.
 *
 * The filter is the server's own `ParkingKind`. `apt.dat` publishes one record type with a
 * `kind` field — gate, hangar, tie-down, misc — so the mockup's "gate heavy / gate medium"
 * split is a distinction the data does not make, and inventing it here would mean guessing
 * from `aircraft_types`. The five rows are the same five rows; they say what the index says.
 */

import type { RefObject } from 'react';
import { useGetParkingQuery } from '../../api/instructorApi';
import { useAppDispatch, useAppSelector } from '../../store';
import { AirportDiagram } from './AirportDiagram';
import { Popover } from './Popover';
import {
  PARKING_FILTERS,
  parkingFilterSelected,
  startAtToggled,
  startRunwaySelected,
  startStandSelected,
  type ParkingFilter,
  type StartAtAnchor,
} from './positionDesignSlice';
import { runwaySelected } from './positionSlice';
import { startAtPopoverId } from './startAt';
import { useLoadedIcao, useRunways } from './usePositionData';

/**
 * `Record<ParkingFilter, string>` and not a loose map: `ParkingFilter` is `'all'` plus the
 * generated `ParkingKind`, so a kind added on the server fails the typecheck here rather
 * than quietly disappearing from the sidebar.
 */
const FILTER_LABEL: Record<ParkingFilter, string> = {
  all: 'All',
  gate: 'Gates',
  tie_down: 'Tie-downs',
  hangar: 'Hangars',
  misc: 'Other',
};

const KIND_LABEL: Record<Exclude<ParkingFilter, 'all'>, string> = {
  gate: 'Gate',
  tie_down: 'Tie-down',
  hangar: 'Hangar',
  misc: 'Other',
};

/**
 * Two triggers mount this component — the header's "Start at" and the bottom bar's "Pick
 * stand / gate" — and only the one whose `anchor` the slice names renders the open panel.
 * The bottom-bar instance floats *above* its trigger; the header's hangs below.
 */
export function StartAtPopover({
  anchor,
  triggerRef,
}: {
  readonly anchor: StartAtAnchor;
  readonly triggerRef: RefObject<HTMLElement | null>;
}) {
  const dispatch = useAppDispatch();
  const icao = useLoadedIcao();
  const open = useAppSelector(
    (state) =>
      state.positionDesign.startAtOpen && state.positionDesign.startAtAnchor === anchor,
  );
  const selectedRunway = useAppSelector((state) => state.positionDesign.selectedRunway);
  const selectedStand = useAppSelector((state) => state.positionDesign.selectedStand);
  const parkingFilter = useAppSelector((state) => state.positionDesign.parkingFilter);
  const legacyRunwayIdent = useAppSelector((state) => state.position.selectedRunwayIdent);

  const { runways } = useRunways();
  // Fetched unfiltered so the "N of M" count can say how many were filtered OUT; the
  // filtering itself is one predicate over a list the popover already holds.
  const { data: stands, isError: standsFailed } = useGetParkingQuery(
    { icao },
    { skip: icao === '' },
  );
  const allStands = stands ?? [];
  const shownStands =
    parkingFilter === 'all'
      ? allStands
      : allStands.filter((stand) => stand.kind === parkingFilter);

  function selectRunway(ident: string) {
    dispatch(startRunwaySelected(ident));
    if (legacyRunwayIdent !== ident) {
      dispatch(runwaySelected(ident));
    }
  }

  return (
    <Popover
      id={startAtPopoverId(anchor)}
      open={open}
      onClose={() => {
        dispatch(startAtToggled(anchor));
      }}
      triggerRef={triggerRef}
      className={
        anchor === 'bottombar'
          ? 'pos-popover pos-startat pos-startat--above'
          : 'pos-popover pos-startat'
      }
    >
      <div className="pos-startat__sidebar">
        <div className="pos-startat__section">
          <h3 className="pos-startat__section-title">Runways</h3>
          <ul className="pos-startat__list">
            {/*
              The ILS badge reads `runway.ils`, which the runway record already carries —
              `GET …/runways/{ident}/ils` returns that very field, so asking the server once
              per row would be the same answer eight times over.
            */}
            {runways.map((runway) => (
              <li key={runway.ident}>
                <button
                  type="button"
                  className={
                    runway.ident === selectedRunway
                      ? 'pos-startat__item pos-startat__item--selected'
                      : 'pos-startat__item'
                  }
                  onClick={() => {
                    selectRunway(runway.ident);
                  }}
                >
                  <span className="pos-mono">
                    {runway.ident}
                    {runway.ils == null ? '' : '·ILS'}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {runways.length === 0 && (
            <p className="pos-startat__empty">No runway in this navigation data.</p>
          )}
        </div>
        <div className="pos-startat__section">
          <h3 className="pos-startat__section-title">Parking type</h3>
          <ul className="pos-startat__list">
            {PARKING_FILTERS.map((filter) => (
              <li key={filter}>
                <button
                  type="button"
                  className={
                    filter === parkingFilter
                      ? 'pos-startat__item pos-startat__item--selected'
                      : 'pos-startat__item'
                  }
                  onClick={() => {
                    dispatch(parkingFilterSelected(filter));
                  }}
                >
                  {FILTER_LABEL[filter]}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <AirportDiagram
        stands={shownStands}
        runways={runways}
        selectedStand={selectedStand}
        onSelect={(name) => {
          dispatch(startStandSelected(name));
        }}
      />

      <div className="pos-startat__stands">
        <p className="pos-startat__stands-count">
          {String(shownStands.length)} of {String(allStands.length)}
        </p>
        {standsFailed && (
          <p className="pos-startat__empty">The parking of {icao} could not be read.</p>
        )}
        <ul className="pos-startat__stands-list">
          {/* Name + index: real apt.dat parking names repeat (see AirportDiagram). */}
          {shownStands.map((stand, index) => (
            <li key={`${stand.name}#${String(index)}`}>
              <button
                type="button"
                className={
                  stand.name === selectedStand
                    ? 'pos-startat__stand pos-startat__stand--selected'
                    : 'pos-startat__stand'
                }
                onClick={() => {
                  dispatch(startStandSelected(stand.name));
                }}
              >
                <span className="pos-mono">{stand.name}</span>
                <span className="pos-startat__stand-type">{KIND_LABEL[stand.kind]}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </Popover>
  );
}
