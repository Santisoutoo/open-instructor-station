/**
 * The header's airport type-ahead.
 *
 * **Every airport in the simulator, not a curated list.** The index holds tens of
 * thousands, so nothing is filtered client-side — the query goes to the server, bounded,
 * and the server ranks it. Which is also why it is debounced: a keystroke is not a request.
 *
 * Choosing a result is the same commit as pressing "Load", so the mirrored
 * `airportSelected` dispatch onto the shared `positionSlice` lives in the one place that
 * knows about both slices, and its same-ICAO guard applies here too.
 */

import { useEffect, useState, type RefObject } from 'react';
import { useSearchAirportsQuery } from '../../api/instructorApi';
import { useAppDispatch, useAppSelector } from '../../store';
import { Popover } from './Popover';
import { formatRunwayLength } from './format';
import { airportMenuClosed } from './positionDesignSlice';

/** A keystroke is not a request. Long enough to skip most of a typed ICAO code. */
const DEBOUNCE_MS = 250;

/** Below this, a query matches too much to be worth asking about. */
const MIN_QUERY_LENGTH = 2;

export function AirportMenu({
  triggerRef,
  onChoose,
}: {
  readonly triggerRef: RefObject<HTMLElement | null>;
  readonly onChoose: (icao: string) => void;
}) {
  const dispatch = useAppDispatch();
  const open = useAppSelector((state) => state.positionDesign.airportMenuOpen);
  const text = useAppSelector((state) => state.positionDesign.icaoInput);
  const [debounced, setDebounced] = useState('');

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setDebounced(text.trim());
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(handle);
    };
  }, [text]);

  const shouldSearch = open && debounced.length >= MIN_QUERY_LENGTH;
  const {
    data: results,
    isFetching,
    isError,
  } = useSearchAirportsQuery({ query: debounced }, { skip: !shouldSearch });

  return (
    <Popover
      id="pos-airport-menu"
      open={open}
      onClose={() => {
        dispatch(airportMenuClosed());
      }}
      triggerRef={triggerRef}
      className="pos-popover pos-airportmenu"
    >
      {!shouldSearch && (
        <p className="pos-airportmenu__hint">
          Type at least {String(MIN_QUERY_LENGTH)} characters — an ICAO or IATA code, or a
          name.
        </p>
      )}
      {/*
        A failed search and an empty one are the same picture unless this says which, and
        the instructor spends a while retyping the code before suspecting the station.
      */}
      {shouldSearch && isError && (
        <p className="pos-airportmenu__error">
          The airport index could not be searched. Check the connection to the station.
        </p>
      )}
      {shouldSearch && !isError && (
        <ul className="pos-airportmenu__list" aria-label="Airport search results">
          {results?.length === 0 && !isFetching && (
            <li className="pos-airportmenu__hint">No airport matches “{debounced}”.</li>
          )}
          {results?.map((airport) => (
            <li key={airport.icao}>
              <button
                type="button"
                className="pos-airportmenu__result"
                onClick={() => {
                  onChoose(airport.icao);
                }}
              >
                <span className="pos-mono">{airport.icao}</span>
                <span className="pos-airportmenu__result-name">{airport.name}</span>
                <span className="pos-airportmenu__result-meta pos-mono">
                  {airport.longest_runway_m == null
                    ? '—'
                    : formatRunwayLength(airport.longest_runway_m)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Popover>
  );
}
