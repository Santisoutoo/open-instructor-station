/**
 * Airport selection: type-ahead over the whole index.
 *
 * **Every airport in the simulator, not a curated list.** The index holds tens of
 * thousands, so this never renders a full list and never filters client-side — the query
 * goes to the server, bounded, and the server ranks it. Which is also why the search is
 * debounced: a keystroke is not a request.
 *
 * Before anything is typed it shows the airports used recently, because an instructor
 * running a lesson returns to the same two or three fields all afternoon.
 */

import { useEffect, useId, useRef, useState } from 'react';
import { useSearchAirportsQuery } from '../../api/instructorApi';
import { useAppDispatch, useAppSelector } from '../../store';
import { formatRunwayLength } from './placements';
import { airportSelected } from './positionSlice';

/** A keystroke is not a request. Long enough to skip most of a typed ICAO code. */
const DEBOUNCE_MS = 250;

/** Below this, a query matches too much to be worth asking about. */
const MIN_QUERY_LENGTH = 2;

export function AirportSearch() {
  const dispatch = useAppDispatch();
  const selectedIcao = useAppSelector((state) => state.position.selectedIcao);
  const recentIcaos = useAppSelector((state) => state.position.recentIcaos);

  const [text, setText] = useState('');
  const [debounced, setDebounced] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setDebounced(text.trim());
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(handle);
    };
  }, [text]);

  // ⌘K / Ctrl-K focuses the search, and the hint is visible in the label rather than
  // being folklore the instructor has to be told about.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, []);

  const shouldSearch = debounced.length >= MIN_QUERY_LENGTH;
  const {
    data: results,
    isFetching,
    isError,
  } = useSearchAirportsQuery({ query: debounced }, { skip: !shouldSearch });

  function choose(icao: string) {
    dispatch(airportSelected(icao));
    setText('');
    setDebounced('');
  }

  return (
    <div className="airport-search">
      <label className="airport-search__label" htmlFor={listId}>
        Airport
        <span className="airport-search__shortcut" aria-hidden="true">
          ⌘K
        </span>
      </label>
      <input
        id={listId}
        ref={inputRef}
        className="airport-search__input"
        type="search"
        autoComplete="off"
        placeholder="ICAO, IATA or name — e.g. LEMD, MAD, Barajas"
        value={text}
        onChange={(event) => {
          setText(event.target.value);
        }}
      />

      {!shouldSearch && recentIcaos.length > 0 && (
        <ul className="airport-search__results" aria-label="Recent airports">
          {recentIcaos.map((icao) => (
            <li key={icao}>
              <button
                type="button"
                className="airport-search__result"
                onClick={() => {
                  choose(icao);
                }}
              >
                <span className="mono">{icao}</span>
                <span className="airport-search__result-meta">
                  {icao === selectedIcao ? 'Selected' : 'Recent'}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {/*
        A failed search and an empty one are the same picture unless this says which, and
        the instructor spends a while retyping the code before suspecting the station.
        Every other picker in this panel reports its own failure; so does this one.
      */}
      {shouldSearch && isError && (
        <p className="panel__error">
          The airport index could not be searched. Check the connection to the station.
        </p>
      )}

      {shouldSearch && !isError && (
        <ul className="airport-search__results" aria-label="Airport search results">
          {results?.length === 0 && !isFetching && (
            <li className="airport-search__empty">No airport matches “{debounced}”.</li>
          )}
          {results?.map((airport) => (
            <li key={airport.icao}>
              <button
                type="button"
                className="airport-search__result"
                onClick={() => {
                  choose(airport.icao);
                }}
              >
                <span className="mono">{airport.icao}</span>
                <span className="airport-search__result-name">{airport.name}</span>
                <span className="airport-search__result-meta">
                  {airport.longest_runway_m == null
                    ? '—'
                    : formatRunwayLength(airport.longest_runway_m)}
                </span>
                {airport.has_procedures && (
                  <span className="dot dot--info" title="Has published procedures" />
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
