import type { RefObject } from 'react';
import { AirportDiagram } from './AirportDiagram';
import { Popover } from './Popover';
import {
  PARKING_FILTERS,
  RUNWAY_IDS,
  parkingFilterSelected,
  startAtToggled,
  startRunwaySelected,
  startStandSelected,
  type ParkingFilter,
  type RunwayId,
} from './positionDesignSlice';
import { runwaySelected } from './positionSlice';
import { RUNWAYS, STANDS, standMatchesFilter } from './sampleData';
import { useAppDispatch, useAppSelector } from '../../store';

const FILTER_LABEL: Record<ParkingFilter, string> = {
  all: 'All',
  'gate-heavy': 'Gate heavy',
  'gate-medium': 'Gate medium',
  misc: 'Miscellaneous',
  'tie-down': 'Tie-down',
};

/**
 * The Start-at popover: runway/helipad list + parking-type list on the left, the airport
 * diagram and a filtered, scrollable stand list on the right. Selecting a runway here is
 * the other place the design doc's mirrored `runwaySelected` dispatch happens (the first is
 * the runway strip); both use the same same-value guard against the legacy slice.
 */
export function StartAtPopover({
  triggerRef,
}: {
  readonly triggerRef: RefObject<HTMLElement | null>;
}) {
  const dispatch = useAppDispatch();
  const open = useAppSelector((state) => state.positionDesign.startAtOpen);
  const selectedRunway = useAppSelector((state) => state.positionDesign.selectedRunway);
  const selectedStand = useAppSelector((state) => state.positionDesign.selectedStand);
  const parkingFilter = useAppSelector((state) => state.positionDesign.parkingFilter);
  const legacyRunwayIdent = useAppSelector((state) => state.position.selectedRunwayIdent);

  const filteredStands = STANDS.filter((stand) => standMatchesFilter(parkingFilter, stand.type));

  function selectRunway(id: RunwayId) {
    dispatch(startRunwaySelected(id));
    if (legacyRunwayIdent !== id) {
      dispatch(runwaySelected(id));
    }
  }

  function selectStand(id: string) {
    dispatch(startStandSelected(id));
  }

  return (
    <Popover
      id="pos-startat-popover"
      open={open}
      onClose={() => {
        dispatch(startAtToggled());
      }}
      triggerRef={triggerRef}
      className="pos-popover pos-startat"
    >
      <div className="pos-startat__sidebar">
        <div className="pos-startat__section">
          <h3 className="pos-startat__section-title">Runways and helipads</h3>
          <ul className="pos-startat__list">
            {RUNWAY_IDS.map((id) => {
              const runway = RUNWAYS[id];
              const hasIls = runway.kind === 'runway' && runway.ils !== null;
              return (
                <li key={id}>
                  <button
                    type="button"
                    className={
                      id === selectedRunway
                        ? 'pos-startat__item pos-startat__item--selected'
                        : 'pos-startat__item'
                    }
                    onClick={() => {
                      selectRunway(id);
                    }}
                  >
                    <span className="pos-mono">
                      {id}
                      {hasIls ? '·ILS' : ''}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
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

      <AirportDiagram selectedStand={selectedStand} onSelect={selectStand} />

      <div className="pos-startat__stands">
        <p className="pos-startat__stands-count">
          {String(filteredStands.length)} of {String(STANDS.length)}
        </p>
        <ul className="pos-startat__stands-list">
          {filteredStands.map((stand) => (
            <li key={stand.id}>
              <button
                type="button"
                className={
                  stand.id === selectedStand
                    ? 'pos-startat__stand pos-startat__stand--selected'
                    : 'pos-startat__stand'
                }
                onClick={() => {
                  selectStand(stand.id);
                }}
              >
                <span className="pos-mono">{stand.id}</span>
                <span className="pos-startat__stand-type">{stand.type}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </Popover>
  );
}
