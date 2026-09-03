/**
 * The startup airport-selection gate.
 *
 * A blocking, full-screen guard that mounts **before** the Instructor Panel shell (header,
 * tab bar, panel host, status bar) and stays up until an airport has been resolved against
 * the navigation index. Mounted from `App.tsx` in place of the whole shell (`gateOpen &&
 * <AirportGate />`), never as a `position: fixed` overlay on top of it.
 *
 * A sibling implementation of `features/position/AirportMenu.tsx`'s search pattern, not a
 * reuse of it: that component is wired to `positionDesignSlice` and a `Popover` anchored to a
 * header trigger, neither of which exists before the shell does. `DEBOUNCE_MS` and
 * `MIN_QUERY_LENGTH` are sibling copies of its own constants.
 *
 * The navdata-not-indexed sub-state reuses `features/position/gate.ts`'s `navdataGate()`
 * directly — a pure function with no slice coupling, so importing it is calling a library,
 * not editing the Position manager. The gate never reads `connection`/WebSocket state:
 * `ConnectionBadge` stays the sole owner of "is the simulator link up."
 */

import type { SerializedError } from '@reduxjs/toolkit';
import type { FetchBaseQueryError } from '@reduxjs/toolkit/query';
import { useEffect, useState, type KeyboardEvent } from 'react';
import {
  instructorApi,
  useBuildNavdataIndexMutation,
  useGetNavdataStatusQuery,
  useSearchAirportsQuery,
} from '../../api/instructorApi';
import { useAppDispatch, useAppSelector } from '../../store';
import { useLazyGetAirportQuery } from '../map/mapApi';
import { navdataGate } from '../position/gate';
import { airportLoaded } from '../position/positionDesignSlice';
import { airportSelected } from '../position/positionSlice';
import { errorMessageFor } from './errorMessage';
import {
  MIN_QUERY_LENGTH,
  queryTyped,
  resolveFailed,
  resolveRequested,
  resolveSucceeded,
} from './startupSlice';
import './AirportGate.css';

/** A keystroke is not a request. Long enough to skip most of a typed ICAO code. */
const DEBOUNCE_MS = 250;

/** A full-screen gate has more room than the header popover's `limit: 12`, but 8 keeps the
 * touch-target list one screen-height on a tablet portrait. */
const RESULT_LIMIT = 8;

/** How often to re-read the navdata status while an index build is running. */
const BUILD_POLL_MS = 1000;

/** Read the cached navdata status without subscribing to it or issuing a request. */
const useGetNavdataStatusState = instructorApi.endpoints.getNavdataStatus.useQueryState;

function NavdataBlock({
  reason,
  canBuild,
  fraction,
}: {
  readonly reason: string;
  readonly canBuild: boolean;
  readonly fraction: number | null;
}) {
  const [buildIndex, buildState] = useBuildNavdataIndexMutation();
  return (
    <div className="startup-gate__navdata">
      <p className="startup-gate__navdata-reason">{reason}</p>
      {fraction !== null && (
        <div
          className="startup-gate__navdata-bar"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(fraction * 100)}
        >
          <span style={{ width: `${String(Math.round(fraction * 100))}%` }} />
        </div>
      )}
      {canBuild && (
        <button
          type="button"
          className="startup-gate__navdata-build"
          disabled={buildState.isLoading}
          onClick={() => {
            void buildIndex();
          }}
        >
          {buildState.isLoading ? 'Starting…' : 'Build index'}
        </button>
      )}
    </div>
  );
}

export function AirportGate() {
  const dispatch = useAppDispatch();
  const status = useAppSelector((state) => state.startup.status);
  const query = useAppSelector((state) => state.startup.query);
  const icao = useAppSelector((state) => state.startup.icao);
  const name = useAppSelector((state) => state.startup.name);
  const errorMessage = useAppSelector((state) => state.startup.errorMessage);

  // Snapshot the remembered airport once, from the values `startupSync.ts` already dispatched
  // before this component's first render (`main.tsx` calls `initStartupSync(store)` before
  // `createRoot().render(...)`). Frozen so it survives further edits to `query` — the
  // "Continue with…" button only shows while the input still reads exactly what was
  // remembered, never after the instructor has changed it.
  const [remembered] = useState(() => ({ icao: query, name }));

  const [debounced, setDebounced] = useState('');
  const [highlighted, setHighlighted] = useState<number | null>(null);
  const [suggestionsCollapsed, setSuggestionsCollapsed] = useState(false);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setDebounced(query.trim());
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(handle);
    };
  }, [query]);

  // Reset the keyboard-navigation state whenever `query` changes — a new list of results is
  // coming, so a stale highlight or a stale "Escape collapsed it" must not survive onto it.
  // Adjusted during render (React's own pattern for "state that follows a prop/value"), not in
  // an effect: a `setState` synchronously inside an effect body is exactly the cascading-render
  // shape `react-hooks/set-state-in-effect` flags.
  const [queryAtLastReset, setQueryAtLastReset] = useState(query);
  if (query !== queryAtLastReset) {
    setQueryAtLastReset(query);
    setHighlighted(null);
    setSuggestionsCollapsed(false);
  }

  const cachedNavdata = useGetNavdataStatusState();
  const { data: navdataStatus, isError: navdataIsError } = useGetNavdataStatusQuery(undefined, {
    pollingInterval: cachedNavdata.data?.state === 'building' ? BUILD_POLL_MS : 0,
    skipPollingIfUnfocused: true,
  });
  const gate = navdataGate(navdataStatus, navdataIsError);

  const shouldSearch =
    gate.kind === 'ready' && status === 'searching' && debounced.length >= MIN_QUERY_LENGTH;
  const {
    data: results,
    isFetching,
    isError: searchIsError,
  } = useSearchAirportsQuery({ query: debounced, limit: RESULT_LIMIT }, { skip: !shouldSearch });
  const options = results ?? [];

  const [triggerGetAirport] = useLazyGetAirportQuery();

  /** `noUncheckedIndexedAccess` means `options[highlighted]` is `AirportSummary | undefined`
   * regardless of the `highlighted !== null` guard — computed once so every consumer narrows
   * off the same value instead of re-indexing (and re-widening) it. */
  const highlightedOption = highlighted !== null ? options[highlighted] : undefined;

  function resolve(rawText: string) {
    const targetIcao = rawText.trim().toUpperCase();
    if (targetIcao.length < MIN_QUERY_LENGTH) {
      return;
    }
    dispatch(resolveRequested(targetIcao));
    void triggerGetAirport(targetIcao)
      .unwrap()
      .then((airport) => {
        dispatch(resolveSucceeded({ icao: airport.icao, name: airport.name }));
        // Mirroring `airportSelected` onto `positionSlice` is "the calling component's job"
        // per `positionDesignSlice.airportLoaded`'s own docstring — this is that component.
        dispatch(airportSelected(airport.icao));
        dispatch(airportLoaded(airport.icao));
      })
      .catch((error: FetchBaseQueryError | SerializedError) => {
        if ('status' in error && error.status === 503) {
          // Navdata dropped out from under the resolve (a race, or the poll has not caught
          // up yet). Not a resolve failure: invalidate the cached status and fall back to
          // searching/idle — the navdata-not-indexed sub-state (already polling) takes over.
          dispatch(instructorApi.util.invalidateTags(['NavdataStatus']));
          dispatch(queryTyped(rawText));
          return;
        }
        dispatch(resolveFailed(errorMessageFor(error, targetIcao)));
      });
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (options.length === 0) {
        return;
      }
      setSuggestionsCollapsed(false);
      setHighlighted((current) =>
        current === null ? 0 : Math.min(current + 1, options.length - 1),
      );
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (options.length === 0) {
        return;
      }
      setSuggestionsCollapsed(false);
      setHighlighted((current) =>
        current === null ? options.length - 1 : Math.max(current - 1, 0),
      );
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      resolve(highlightedOption?.icao ?? query);
      return;
    }
    if (event.key === 'Escape') {
      setSuggestionsCollapsed(true);
    }
  }

  const listboxVisible =
    shouldSearch && !suggestionsCollapsed && !searchIsError && options.length > 0;
  const showRememberedButton =
    remembered.icao !== '' && status === 'searching' && query === remembered.icao;

  return (
    <section
      className="startup-gate"
      role="dialog"
      aria-modal="true"
      aria-label="Choose an airport"
    >
      {gate.kind !== 'ready' ? (
        <div className="startup-gate__card">
          <h1>Open Instructor Station</h1>
          <NavdataBlock
            reason={gate.reason}
            canBuild={gate.kind === 'blocked' && gate.canBuild}
            fraction={gate.kind === 'building' ? gate.fraction : null}
          />
        </div>
      ) : (
        <div className="startup-gate__card">
          <h1>Open Instructor Station</h1>
          <p>Choose the airport for this session.</p>

          {showRememberedButton && (
            <button
              type="button"
              className="startup-gate__remembered"
              onClick={() => {
                resolve(remembered.icao);
              }}
            >
              Continue with {remembered.name ?? remembered.icao}
            </button>
          )}

          <input
            role="combobox"
            aria-expanded={listboxVisible}
            aria-controls="startup-gate-listbox"
            aria-activedescendant={
              highlightedOption ? `startup-gate-option-${highlightedOption.icao}` : undefined
            }
            autoFocus
            disabled={status === 'resolving'}
            value={query}
            placeholder="ICAO, IATA or airport name"
            onChange={(event) => {
              dispatch(queryTyped(event.target.value));
            }}
            onKeyDown={handleKeyDown}
          />

          {status === 'idle' && (
            <p className="startup-gate__hint">
              Type at least {String(MIN_QUERY_LENGTH)} characters — an ICAO or IATA code, or a
              name.
            </p>
          )}

          {status === 'searching' && searchIsError && (
            <p className="startup-gate__error">
              The airport index could not be searched. Check the connection to the station.
            </p>
          )}

          {status === 'searching' &&
            !searchIsError &&
            shouldSearch &&
            options.length === 0 &&
            !isFetching && (
              <p className="startup-gate__hint">No airport matches &quot;{debounced}&quot;.</p>
            )}

          {listboxVisible && (
            <ul className="startup-gate__listbox" role="listbox" id="startup-gate-listbox">
              {options.map((airport, index) => (
                <li
                  key={airport.icao}
                  role="option"
                  id={`startup-gate-option-${airport.icao}`}
                  aria-selected={index === highlighted}
                  className="startup-gate__option"
                >
                  <button
                    type="button"
                    onClick={() => {
                      resolve(airport.icao);
                    }}
                  >
                    <span className="startup-gate__option-icao">{airport.icao}</span>
                    <span className="startup-gate__option-name">{airport.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {status === 'resolving' && <p className="startup-gate__loading">Loading {icao}…</p>}

          {status === 'error' && <p className="startup-gate__error">{errorMessage}</p>}
        </div>
      )}
    </section>
  );
}
